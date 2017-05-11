# extract-gk100d
Extract xp3 files of Gaokao Love 100 Days

`python3 extractdata.py -e data.xp3 output/`

* Should work with Steam and Disc versions.
* Can't extract filename, the extensions are guessed.
  * Depends on `python3-magic` (Debain) or `file-magic` (pypi)
* Should also work with many unencrypted Kirikiri XP3 files. (without -e option)

This program is free software. It comes without any warranty, to
the extent permitted by applicable law. You can redistribute it
and/or modify it under the terms of the Do What The Fuck You Want
To Public License, Version 2, as published by Sam Hocevar. See
http://www.wtfpl.net/ for more details.
