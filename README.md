# Usage and requirements

You need:

* Python 3 (`brew install python3`) because it uses async/await and asyncio
* Xcode CLI tools (I think)

Then do:

```
./macpack.py <your executable here>
```

Everything that your executable uses should then be copied into the same folder
that your binary is. When your main binary is run next, it will look in its own
directory for the dylibs it uses. Those dylibs will look in the same directory for
dylibs they depend on, too, even if your main binary does not use them.

You can then distribute the whole folder as one.

# Background
It will parse out the executable's dependencies (using `otool -L`) and their
dependencies recursively, filtering out system libraries. When the tree
is built, it will copy the libraries to your program's folder and then patch
everything that it is aware of (using `install_name_tool`). It should be able
to handle different symbolic links and all that correctly

# Credits
Inspired by [macdylibbundler](https://github.com/auriamg/macdylibbundler), it does
the same basic thing except with less options (at the moment) and it builds a full
dependency tree

# License
Copyright (c) 2016 Caleb Hearon

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
