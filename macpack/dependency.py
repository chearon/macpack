import argparse
import asyncio
import re
import pathlib
import subprocess
import re
import os
import sys

class Dependency:
  def __init__(self, path):
    self.path = pathlib.PosixPath(path).resolve(strict=True)
    self.symlinks = []
    self.dependencies = []
    self.rpaths = []

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
    # find all rpaths associated with this item
    self.rpaths = await self.find_rpaths()

    process = await asyncio.create_subprocess_exec('otool', '-L', str(self.path),
      stdout = subprocess.PIPE,
      stderr = subprocess.PIPE)

    (out, err) = await process.communicate()

    paths = self.extract_paths_from_output(out.decode('utf-8'))
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


  async def find_rpaths(self):
    process = await asyncio.create_subprocess_exec('otool', '-l', str(self.path),
                                                   stdout=subprocess.PIPE,
                                                   stderr=subprocess.PIPE)
    out, err = await process.communicate()
    out = out.decode('utf-8')
    return re.findall('LC_RPATH\n.*\n.*path ([a-zA-Z0-9/ ]+) \(', out, re.MULTILINE)

  def find_in_rpath(self, library_name):
    for rpath in self.rpaths:
      if os.path.exists(rpath + library_name):
        return rpath + library_name

    return None

  def extract_dep(self, line):
    path = line[1:line.find(' (compatibility version ')]

    # if path is relative to loader, we substitute it with the path of the requester
    if path.startswith('@loader_path'):
      path = path.replace('@loader_path', str(self.path.parent))

    if path.startswith('@rpath'):
      path = self.find_in_rpath(path.replace('@rpath', ''))

    if path is None:
      print('Could not resolve %s in rpath' % line, file=sys.stderr)

    return path


  def is_dep_line(line):
    return len(line) > 0 and line[0] == '\t'

  def extract_paths_from_output(self, s):
    return [self.extract_dep(l) for l in s.split('\n') if Dependency.is_dep_line(l)]

  def deps_from_paths(paths):
    dependencies = []
    failed_paths = []

    for path in paths:
      if path is None:
        continue

      try:
        dependencies.append(Dependency(path))
      except FileNotFoundError:
        failed_paths.append(path)

    return (dependencies, failed_paths)


