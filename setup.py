import setuptools
import os

try:
  import pypandoc
  description = pypandoc.convert('README.md', 'rst') if os.path.exists('README.md') else ''
except ImportError:
  description = ''

setuptools.setup(
  name = 'macpack',
  packages = setuptools.find_packages(),
  version = '1.0.3',
  description = 'Makes a macOS binary redistributable by searching the dependency tree and copying/patching non-system libraries.',
  long_description = description,
  author = 'Caleb Hearon',
  author_email = 'caleb@chearon.net',
  url = 'https://github.com/chearon/macpack',
  download_url = 'https://github.com/chearon/macpack/tarball/v1.0.3',
  keywords = ['macos', 'bundle', 'package', 'redistribute', 'redistributable', 'install_name_tool', 'otool', 'mach'],
  classifiers = [],
  entry_points = {
    'console_scripts': ['macpack=macpack.patcher:main'],
  }
)
