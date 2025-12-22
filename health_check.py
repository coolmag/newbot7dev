"""
🆕 health_check.py - Система мониторинга здоровья бота
"""

import psutil
import time
from typing import Dict, Any
from datetime import datetime

class HealthMonitor:
    def __init__(self):
        self.start_time = time.time()
        self.last_error_time = None
        self.error_count = 0
        self.total_requests = 0
        self.successful_downloads = 0
        self.failed_downloads = 0
    
    def record_error(self):
        """Records an error occurrence."""
        self.error_count += 1
        self.last_error_time = datetime.now()
    
    def record_download(self, success: bool):
        """Records a download attempt."""
        if success:
            self.successful_downloads += 1
        else:
            self.failed_downloads += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Returns current system stats."""
        process = psutil.Process()
        uptime = time.time() - self.start_time
        
        return {
            "status": "healthy" if self.error_count < 10 else "degraded",
            "uptime_seconds": int(uptime),
            "uptime_hours": round(uptime / 3600, 2),
            "memory_mb": round(process.memory_info().rss / 1024 / 1024, 2),
            "cpu_percent": process.cpu_percent(interval=0.1),
            "error_count": self.error_count,
            "last_error": self.last_error_time.isoformat() if self.last_error_time else None,
            "downloads": {
                "successful": self.successful_downloads,
                "failed": self.failed_downloads,
                "success_rate": round(
                    self.successful_downloads / max(1, self.successful_downloads + self.failed_downloads) * 100,
                    2
                )
            }
        }
