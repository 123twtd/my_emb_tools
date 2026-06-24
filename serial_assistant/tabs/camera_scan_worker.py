"""视频流设备扫描线程"""

from PyQt5.QtCore import QThread, pyqtSignal


class CameraScanWorker(QThread):
    """后台扫描摄像头，带进度回调"""

    scan_progress = pyqtSignal(int, int, str)
    scan_finished = pyqtSignal(list)
    scan_failed = pyqtSignal(str)

    def __init__(self, broadcaster, parent=None):
        super().__init__(parent)
        self._broadcaster = broadcaster

    def run(self):
        try:
            if self._broadcaster is None:
                self.scan_failed.emit("视频服务未初始化")
                return

            def on_progress(current, total, message):
                self.scan_progress.emit(current, total, message)

            devices = self._broadcaster.enumerate_devices(
                refresh=True, progress_callback=on_progress
            )
            self.scan_finished.emit(devices)
        except Exception as e:
            self.scan_failed.emit(str(e))
