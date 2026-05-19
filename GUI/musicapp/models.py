from django.db import models
from django.utils.timezone import now

class DownloadedTrack(models.Model):
    video_id = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    title = models.CharField(max_length=255, db_index=True)
    artist = models.CharField(max_length=255, db_index=True)
    album = models.CharField(max_length=255, blank=True, null=True)
    file_path = models.CharField(max_length=1000, unique=True)
    downloaded_at = models.DateTimeField(default=now)

    class Meta:
        verbose_name = "Downloaded Track"
        verbose_name_plural = "Downloaded Tracks"
        ordering = ['-downloaded_at']
        
    def __str__(self):
        return f"{self.artist} - {self.title}"
