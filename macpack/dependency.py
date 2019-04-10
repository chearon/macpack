import argparse
import asyncio
import re
import pathlib
import subprocess
import re
import os
import sys


class Dependency:
  def __init__(self, reference, file_path):
    self.path = file_path
    self.referred_as = {reference}
    self.dependencies = []
    self.rpaths = []

  def __repr__(self):
    return ('Dependency(\'' + str(self.path) + '\', '
            'referred_as=' + str(len(self.referred_as)) + '\', '
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

  def merge(self, dependency):
    for reference in dependency.referred_as:
      self.referred_as.add(reference)

    for d in dependency.dependencies:
      self.dependencies.append(d)

  async def find_dependencies(self):
    # find all rpaths associated with this item
    self.rpaths = await self.find_rpaths()

    process = await asyncio.create_subprocess_exec('otool', '-L', str(self.path),
      stdout = subprocess.PIPE,
      stderr = subprocess.PIPE)

    (out, err) = await process.communicate()

    references = self.extract_references_from_output(out.decode('utf-8'))
    (deps, failed_references) = self.deps_from_references(references)

    self.dependencies = deps

    return (deps, failed_references)

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

  def resolve_in_rpath(self, library_name):
    for rpath in self.rpaths:
      if os.path.exists(rpath + library_name):
        return os.path.realpath(rpath + library_name)
    return None

  def extract_referral(self, line):
    path = line[1:line.find(' (compatibility version ')]
    return path


  def is_dep_line(line):
    return len(line) > 0 and line[0] == '\t'

  def extract_references_from_output(self, s):
    return [self.extract_referral(l) for l in s.split('\n') if Dependency.is_dep_line(l)]


  def file_path_from_reference(self, reference):
    # if path is relative to loader, we substitute it with the path of the requester
    result = reference
    if reference.startswith('@loader_path'):
      result = reference.replace('@loader_path', str(self.path.parent))

    if reference.startswith('@rpath'):
      result = self.resolve_in_rpath(reference.replace('@rpath', ''))

    if result is None:
      print('Could not resolve %s in rpath' % reference, file=sys.stderr)
    else:
      result = pathlib.PosixPath(result).resolve(strict=True)

    return result


  def deps_from_references(self, references):
    dependencies = []
    failed_references = []

    for reference in references:
      if reference is None:
        continue

      try:
        dependencies.append(Dependency(reference, self.file_path_from_reference(reference)))
      except FileNotFoundError:
        failed_references.append(reference)

    return dependencies, failed_references

