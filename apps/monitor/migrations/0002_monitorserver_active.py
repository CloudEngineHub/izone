# Generated by Django 2.2.28 on 2024-04-04 23:59

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitor', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='monitorserver',
            name='active',
            field=models.BooleanField(default=True, help_text='用来过滤，无效的不显示', verbose_name='是否有效'),
        ),
    ]
