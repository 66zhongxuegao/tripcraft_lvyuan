"""测试期全局约定。

公网访问监控（tripcraft/services/visit_monitor.py）默认把访客写进项目根 logs/；
跑测试时会经过 TestClient 产生一堆假访问，所以在任何 tripcraft 模块被 import 之前，
把日志目录改到临时目录去。
"""

import os
import tempfile

os.environ.setdefault("TRIPCRAFT_VISIT_LOG_DIR", tempfile.mkdtemp(prefix="tripcraft-visit-log-"))