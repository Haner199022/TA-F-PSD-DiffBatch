# UTF-8
# PyInstaller version metadata embedded into the Windows .exe.
# Shown in File Explorer right-click "Properties → Details".
# Format reference: https://docs.microsoft.com/en-us/windows/win32/menurc/versioninfo-resource
#
# This file is a TEMPLATE — do not edit version_info.txt directly.
# Run tools/render_version.py (build.bat does this automatically) to
# regenerate version_info.txt from _version.py.
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={VERSION_TUPLE},
    prodvers={VERSION_TUPLE},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          u'040904B0',
          [
            StringStruct(u'CompanyName', u'TA-F'),
            StringStruct(u'FileDescription', u'TA-F PSD DiffBatch - Photoshop batch normalizer & script runner'),
            StringStruct(u'FileVersion', u'{VERSION_STR}'),
            StringStruct(u'InternalName', u'TA-F PSD DiffBatch'),
            StringStruct(u'LegalCopyright', u''),
            StringStruct(u'OriginalFilename', u'TA-F PSD DiffBatch.exe'),
            StringStruct(u'ProductName', u'TA-F PSD DiffBatch'),
            StringStruct(u'ProductVersion', u'{VERSION_STR}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
