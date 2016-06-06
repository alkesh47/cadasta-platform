import os
import magic
from datetime import datetime
from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.dispatch import receiver
from django.conf import settings
from django.utils.translation import ugettext as _
from django.contrib.postgres.fields import JSONField

from tutelary.decorators import permissioned_model
from buckets.fields import S3FileField

from core.models import RandomIDModel, ID_FIELD_LENGTH
from .managers import ResourceManager
from .validators import validate_file_type
from .utils import thumbnail, io
from . import messages

content_types = models.Q(app_label='organization', model='project')


@permissioned_model
class Resource(RandomIDModel):
    name = models.CharField(max_length=200)
    description = models.TextField(null=True, blank=True)
    file = S3FileField(upload_to='resources', validators=[validate_file_type])
    original_file = models.CharField(max_length=200)
    file_versions = JSONField(null=True, blank=True)
    mime_type = models.CharField(max_length=50)
    archived = models.BooleanField(default=False)
    last_updated = models.DateTimeField(auto_now=True)
    contributor = models.ForeignKey('accounts.User')
    project = models.ForeignKey('organization.Project')

    objects = ResourceManager()

    class TutelaryMeta:
        perm_type = 'resource'
        path_fields = ('project', 'pk')
        actions = (
            ('resource.list',
             {'description': _("List resources"),
              'permissions_object': 'project',
              'error_message': messages.RESOURCE_LIST}),
            ('resource.add',
             {'description': _("Add new resources"),
              'permissions_object': 'project',
              'error_message': messages.RESOURCE_ADD}),
            ('resource.view',
             {'description': _("View resource"),
              'error_message': messages.RESOURCE_VIEW}),
            ('resource.edit',
             {'description': _("Edit resource"),
              'error_message': messages.RESOURCE_EDIT}),
            ('resource.archive',
             {'description': _("Archive resource"),
              'error_message': messages.RESOURCE_ARCHIVE}),
            ('resource.unarchive',
             {'description': _("Unarchive resource"),
              'error_message': messages.RESOURCE_UNARCHIVE}),
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._orginial_url = self.file.url

    @property
    def file_name(self):
        if not hasattr(self, '_file_name'):
            self._file_name = self.file.url.split('/')[-1]

        return self._file_name

    @property
    def file_type(self):
        return self.file_name.split('.')[-1]

    @property
    def thumbnail(self):
        if not hasattr(self, '_thumbnail'):
            if 'image' in self.mime_type:
                ext = self.file_name.split('.')[-1]
                base_url = self.file.url[:self.file.url.rfind('.')]
                self._thumbnail = base_url + '-128x128.' + ext
            else:
                self._thumbnail = ''
        return self._thumbnail

    @property
    def num_entities(self):
        return ContentObject.objects.filter(resource=self).count()


@receiver(models.signals.pre_save, sender=Resource)
def archive_file(sender, instance, **kwargs):
    if instance._orginial_url != instance.file.url:
        now = str(datetime.now())
        if not instance.file_versions:
            instance.file_versions = {}
        instance.file_versions[now] = instance._orginial_url


@receiver(models.signals.post_save, sender=Resource)
def create_thumbnails(sender, instance, created, **kwargs):
    if created or instance._orginial_url != instance.file.url:
        file = instance.file.open()
        if 'image' in magic.from_file(file.name, mime=True).decode():
            io.ensure_dirs()
            file_name = instance.file.url.split('/')[-1]
            name = file_name[:file_name.rfind('.')]
            ext = file_name.split('.')[-1]
            write_path = os.path.join(settings.MEDIA_ROOT,
                                      'temp',
                                      name + '-128x128.' + ext)

            size = 128, 128

            thumb = thumbnail.make(file, size)
            thumb.save(write_path)
            instance.file.storage.save(name + '-128x128.' + ext,
                                       open(write_path, 'rb'))


class ContentObject(RandomIDModel):
    resource = models.ForeignKey(Resource, related_name='content_objects')

    content_type = models.ForeignKey(ContentType,
                                     on_delete=models.CASCADE,
                                     null=True,
                                     blank=True,
                                     limit_choices_to=content_types)
    object_id = models.CharField(max_length=ID_FIELD_LENGTH,
                                 null=True,
                                 blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')