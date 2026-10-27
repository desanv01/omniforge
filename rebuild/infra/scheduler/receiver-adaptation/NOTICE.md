# Upstream attribution and derivative notice

This artifact targets the Hatchet Python SDK, distribution `hatchet-sdk`, version
1.41.1. Installed distribution metadata identifies its license as MIT.
The official pinned [py/1.41.1 release](https://github.com/hatchet-dev/hatchet/releases/tag/py%2F1.41.1)
and its [monorepo LICENSE](https://raw.githubusercontent.com/hatchet-dev/hatchet/py/1.41.1/LICENSE)
provide the upstream provenance and full terms reproduced below.

Only a six-file patch and hash manifest are distributed here; no complete copied
package, installed environment or private runtime data is included. The installed
distribution inspected for this stage did not include a standalone LICENSE file
in its package/dist-info directories; the pinned upstream notice is included here
now. A later derivative image must retain these upstream copyright and license terms.

MIT License

Copyright (c) 2023-present Hatchet Technologies Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

The changes are an OmniForge-specific pinned derivative, not an untouched SDK or
an upstream endorsement. Stage A modifies copied config.py and connection.py. Stage B adds selected
dispatcher/listener/admin boundaries. Stage C1 changes selected dispatcher event
methods and adds worker/action_listener_process.py event-send ownership only.
