from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0008_attributetemplate"),
    ]

    operations = [
        migrations.AlterField(
            model_name="organization",
            name="lms_type",
            field=models.CharField(
                blank=True,
                choices=[("CANVAS", "Canvas"), ("MOODLE", "Moodle")],
                max_length=500,
                null=True,
            ),
        ),
    ]
