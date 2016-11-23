import argparse
import asyncio
import re
import pathlib
import subprocess

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
