#!/usr/bin/env python3

import argparse
import asyncio
import os
import sys
import subprocess
import pathlib
import re
import shutil

class PatchError(Exception):
  pass

class Dependency:
  def __init__(self, path):
    self.path = pathlib.PosixPath(path).resolve()
    self.symlinks = []
    self.dependencies = []

    if self.path != path:
      self.symlinks.append(str(path))

  def __repr__(self):
    return ('Dependency(\'' + str(self.path) + '\', '
            'symlinks=' + str(len(self.symlinks)) + '\', '
            'dependencies=' + str(len(self.dependencies)) + ')')

  def __eq__(self, b):
    return self.path == b.path

  def is_sys(self):
    is_sys = True
    try:
      self.path.relative_to('/usr/lib')
    except ValueError:
      is_sys = any((p for p in self.path.parts if re.search('.framework$', p)))

    return is_sys

  def add_symlink(self, path):
    if path not in self.symlinks:
      self.symlinks.append(path)

  def merge(self, dependency):
    for s in dependency.symlinks:
      self.add_symlink(s)

    for d in dependency.dependencies:
      self.dependencies.append(d)

  async def find_dependencies(self):
    process = await asyncio.create_subprocess_exec('otool', '-L', str(self.path),
      stdout = subprocess.PIPE,
      stderr = subprocess.PIPE)

    (out, err) = await process.communicate()

    paths = Dependency.extract_paths_from_output(out.decode('utf-8'))
    (deps, failed_paths) = Dependency.deps_from_paths(paths)

    self.dependencies = deps

    return (deps, failed_paths)

  def get_dependencies(self, is_sys = False):
    stack = [self]
    ret = []

    while len(stack) > 0:
      dep = stack.pop()
      for d in dep.get_direct_dependencies(is_sys):
        if d not in ret:
          ret.append(d)
          stack.append(d)

    return ret

  def get_direct_dependencies(self, is_sys = False):
    return [d for d in self.dependencies if is_sys or not d.is_sys()]

  def extract_dep(line):
    return line[1:line.find(' (compatibility version ')]

  def is_dep_line(line):
    return len(line) > 0 and line[0] == '\t'

  def extract_paths_from_output(s):
    return [Dependency.extract_dep(l) for l in s.split('\n') if Dependency.is_dep_line(l)]

  def deps_from_paths(paths):
    dependencies = []
    failed_paths = []

    for path in paths:
      try:
        dependencies.append(Dependency(path))
      except FileNotFoundError:
        failed_paths.append(path)

    return (dependencies, failed_paths)

async def collect(root_dep):
  failed_paths = []
  all_resolved = []
  stack = [[root_dep]]

  while len(stack) > 0:
    resolving_deps = stack.pop()
    results = await asyncio.gather(*[d.find_dependencies() for d in resolving_deps])
    all_resolved += resolving_deps

    to_resolve = []
    for i, deps_and_failed in enumerate(results):
      failed_paths += deps_and_failed[1]

      for j, dep in enumerate(deps_and_failed[0]):
        if not dep.is_sys():
          if dep in all_resolved:
            existing_dep = all_resolved[all_resolved.index(dep)]
          elif dep in to_resolve:
            existing_dep = to_resolve[to_resolve.index(dep)]
          else:
            existing_dep = None

          if existing_dep:
            existing_dep.merge(dep)
            resolving_deps[i].dependencies[j] = existing_dep
          else:
            to_resolve.append(dep)

    if len(to_resolve) > 0: stack.append(to_resolve)

  if len(failed_paths):
    print('Some of the paths in the dependency tree could not be resolved', file=sys.stderr)
    print('Maybe you already bundled {}?'.format(root_dep.path.name), file=sys.stderr)
    if (args.verbose):
      for path in failed_paths:
        print('Could not resolve {}'.format(path), file=sys.stderr)
    else:
      print('Run with -v to see failed paths', file=sys.stderr)

def ensure_dir(path):
  if not os.path.exists(str(path)):
    os.makedirs(str(path))

async def patch(root_dep, dest_path, root_loader_path):
  process_coros = []
  patch_deps = [root_dep] + root_dep.get_dependencies()

  ensure_dir(dest_path)

  for dep in patch_deps:
    if dep == root_dep:
      pargs = ['install_name_tool', str(root_dep.path)]
      loader_path = root_loader_path
    else:
      shutil.copyfile(str(dep.path), str(dest_path / dep.path.name))
      pargs = ['install_name_tool', str(dest_path / dep.path.name)]
      loader_path = pathlib.PurePath('@loader_path')

    pargs += ['-id', str(loader_path / dep.path.name)]

    for dep_dep in dep.get_direct_dependencies():
      pargs += ['-change', str(dep_dep.path), str(loader_path / dep_dep.path.name)]
      for symlink in dep_dep.symlinks:
        pargs += ['-change', symlink, str(loader_path / dep_dep.path.name)]

    process_coros.append(asyncio.create_subprocess_exec(*pargs,
      stdout = subprocess.PIPE,
      stderr = subprocess.PIPE
    ))

  processes = await asyncio.gather(*process_coros)
  results = await asyncio.gather(*[p.communicate() for p in processes])

  did_error = False
  for process, (out, err), dep in zip(processes, results, patch_deps):
    if process.returncode:
      did_error = True
      print('Error patching {}'.format(str(dep.path.name)), file=sys.stderr)
      if args.verbose:
        print(err.decode('utf-8'))

  if did_error: raise PatchError('One or more dependencies could not be patched')

def print_deps_minimal(d):
  deps = d.get_dependencies()

  print(str(len(deps)) + ' total non-system dependenc{}'.format('y' if len(deps) == 1 else 'ies'))

  for i, dep in enumerate(deps):
    dep_slots = [str(deps.index(d) + 1) for d in dep.get_direct_dependencies()]
    s = ', '.join(dep_slots) if len(dep_slots) > 0 else 'No dependencies'
    print(str(i+1) + '\t' + dep.path.name + ' -> ' + s)

def print_deps(d):
  deps = d.get_dependencies()

  print(str(len(deps)) + ' total non-system dependenc{}'.format('y' if len(deps) == 1 else 'ies'))

  for dep in deps:
    print(dep.path.name)
    for dep_dep in dep.get_dependencies():
      print('-> ' + dep_dep.path.name)

def prepatch_output(d):
  print("Patching {}".format(str(args.file)))

  if args.verbose:
    print_deps(d)
  else:
    print_deps_minimal(d)

def get_dest_and_loader_path(root_dep_path, dest_path):
  if dest_path.is_absolute():
    loader_path = dest_path
  else:
    dest_path = root_dep_path.parent / dest_path
    rel_to_binary = os.path.relpath(str(dest_path), str(root_dep_path.parent))
    loader_path = pathlib.PurePath('@loader_path', rel_to_binary)

  return (dest_path, loader_path)

def main(args):
  try:
    d = Dependency(args.file)
  except FileNotFoundError:
    print('{} does not exist!'.format(str(args.file)), file=sys.stderr)
    sys.exit(1)

  loop = asyncio.get_event_loop()

  loop.run_until_complete(collect(d))

  dest_path, root_loader_path = get_dest_and_loader_path(d.path, args.destination)

  prepatch_output(d)

  try:
    loop.run_until_complete(patch(d, dest_path, root_loader_path))
  except PatchError: # the error should have been already printed here
    if not args.verbose: print('Run with -v for more information', file=sys.stderr)
    sys.exit(1)

  n_deps = len(d.get_dependencies())
  print()
  print('{} + {} dependenc{} successfully patched'.format(args.file.name, n_deps, 'y' if n_deps == 1 else 'ies'))

  loop.close()

if __name__ == '__main__':
  parser = argparse.ArgumentParser(description='Copies non-system libraries used by your executable and patches them to work as a standalone bundle')
  parser.add_argument('file', help='file to patch (the root, main binary)', type=pathlib.PurePath)
  parser.add_argument('-v', '--verbose', help='displays more library information and output of install_name_tool', action='store_true')
  parser.add_argument('-d', '--destination', help='destination directory where the binaries will be placed and loaded', type=pathlib.Path, default='../libs')
  args = parser.parse_args()
  main(args)

