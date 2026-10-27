# Upstream attribution and derivative notice

This artifact targets the Hatchet Python SDK, distribution `hatchet-sdk`, version
1.41.1. Installed distribution metadata identifies its license as MIT.
The official pinned [py/1.41.1 release](https://github.com/hatchet-dev/hatchet/releases/tag/py%2F1.41.1)
and its [monorepo LICENSE](https://raw.githubusercontent.com/hatchet-dev/hatchet/py/1.41.1/LICENSE)
provide the upstream provenance and full terms reproduced below.

Only a four-file patch and hash manifest are distributed here; no complete copied
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

The changes are an OmniForge-specific pinned REST derivative, not an untouched
SDK or upstream endorsement. Four copied files are modified: features/workers.py,
clients/v1/api_client.py, clients/rest/api_client.py and clients/rest/rest.py.
REST2 adds a prepared pause and partial-construction ownership seam within those
same four copied files; upstream attribution and license terms remain unchanged.
