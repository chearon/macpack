#!/usr/bin/env python3

import argparse
import asyncio
import os
import sys
import subprocess
import pathlib
import re
import shutil

class Dependency:
  def __init__(self, filename):
    self.path = pathlib.PurePath(os.path.realpath(filename))
    self.symlinks = []
    self.dependencies = []

    if str(self.path) != filename:
      self.symlinks.append(filename)

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

    self.dependencies = Dependency.deps_from_output(out.decode('utf-8'))

    return self.dependencies

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
    return Dependency(line[1:line.find(' (compatibility version ')])

  def is_dep_line(line):
    return len(line) > 0 and line[0] == '\t'

  def deps_from_output(s):
    return [Dependency.extract_dep(l) for l in s.split('\n') if Dependency.is_dep_line(l)]

async def collect(root_dep):
  all_resolved = []
  stack = [[root_dep]]

  while len(stack) > 0:
    resolving_deps = stack.pop()
    results = await asyncio.gather(*[d.find_dependencies() for d in resolving_deps])
    all_resolved += resolving_deps

    to_resolve = []
    for i, result in enumerate(results):
      for j, dep in enumerate(result):
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

async def patch(root_dep):
  process_coroutines = []
  dest_path = pathlib.PurePath(root_dep.path.parent)
  dest_loader_path = pathlib.PurePath('@loader_path')

  if not os.path.exists(str(dest_path)):
    os.makedirs(str(dest_path))

  patch_deps = [root_dep] + root_dep.get_dependencies()

  for dep in patch_deps:
    if dep == root_dep:
      args = ['install_name_tool', str(root_dep.path)]
    else:
      shutil.copyfile(str(dep.path), str(dest_path / dep.path.name))
      args = ['install_name_tool', str(dest_path / dep.path.name)]

    args += ['-id', str(dest_loader_path / dep.path.name)]

    for dep_dep in dep.get_direct_dependencies():
      args += ['-change', str(dep_dep.path), str(dest_loader_path / dep_dep.path.name)]
      for symlink in dep_dep.symlinks:
        args += ['-change', symlink, str(dest_loader_path / dep_dep.path.name)]

    process_coroutines.append(asyncio.create_subprocess_exec(*args, 
      stdout = subprocess.PIPE,
      stderr = subprocess.PIPE
    ))

  processes = await asyncio.gather(*process_coroutines)
  results = await asyncio.gather(*[p.communicate() for p in processes])

  did_error = False
  for process, (out, err), dep in zip(processes, results, patch_deps):
    if process.returncode:
      did_error = True
      print('Error patching {}'.format(dep.filename), file=sys.stderr)
      if args.verbose:
        print(err.decode('utf-8'))

  if did_error: raise Exception('One or more dependencies could not be patched')

  # TODO test for success

def print_deps_minimal(d):
  deps = d.get_dependencies()

  print(str(len(deps)) + ' total non-system dependencies')

  for i, dep in enumerate(deps):
    dep_slots = [str(deps.index(d) + 1) for d in dep.get_direct_dependencies()]
    s = ', '.join(dep_slots) if len(dep_slots) > 0 else 'No dependencies'
    print(str(i+1) + '\t' + dep.path.name + ' -> ' + s)

def print_deps(d):
  deps = d.get_dependencies()

  print(str(len(deps)) + ' total non-system dependencies')

  for dep in deps:
    print(dep.path.name)
    for dep_dep in dep.get_dependencies():
      print('-> ' + dep_dep.path.name)

def main():
  print("Patching {}".format(args.file))
  d = Dependency(args.file)
  loop = asyncio.get_event_loop()

  loop.run_until_complete(collect(d))

  if args.verbose:
    print_deps(d)
  else:
    print_deps_minimal(d)

  try:
    loop.run_until_complete(patch(d))
  except Exception:
    sys.exit(1)

  loop.close()

parser = argparse.ArgumentParser(description='Copies non-system libraries used by your executable and patches them to work as a standalone bundle')
parser.add_argument('--verbose', help='displays more library information and output of install_name_tool', action='store_true')
parser.add_argument('file', help='file to patch (the root, main binary)')
args = parser.parse_args()

if __name__ == '__main__':
  main()

