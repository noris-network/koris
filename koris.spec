# -*- mode: python -*-

block_cipher = None


def Entrypoint(dist, group, name, **kwargs):
    import pkg_resources

    # get toplevel packages of distribution from metadata
    def get_toplevel(dist):
        distribution = pkg_resources.get_distribution(dist)
        if distribution.has_metadata('top_level.txt'):
            return list(distribution.get_metadata('top_level.txt').split())
        else:
            return []

    #kwargs.setdefault('hiddenimports', [])
    #packages = []
    #for distribution in kwargs['hiddenimports']:
    #    packages += get_toplevel(distribution)

    kwargs.setdefault('pathex', [])
    # get the entry point
    ep = pkg_resources.get_entry_info(dist, group, name)
    # insert path of the egg at the verify front of the search path
    kwargs['pathex'] = [ep.dist.location] + kwargs['pathex']
    # script name must not be a valid module name to avoid name clashes on import
    script_path = os.path.join(workpath, name + '-launcher')
    print("creating script for entry point", dist, group, name)
    with open(script_path, 'w') as fh:
        print("import", ep.module_name, file=fh)
        print("%s.%s()" % (ep.module_name, '.'.join(ep.attrs)), file=fh)
        #for package in packages:
        #    print("import", package, file=fh)

    return Analysis(
        [script_path] + kwargs.get('scripts', []),
        **kwargs
    )

from pkg_resources import resource_filename, Requirement

os_service_types = resource_filename(Requirement("os_service_types"),
                                     "os_service_types/data")

os_defaults = resource_filename(Requirement('openstacksdk'), 'openstack/config')

a = Entrypoint('koris', 'console_scripts', 'koris',
               datas=[('koris/provision/userdata/*', 'provision/userdata'),
	              (os_service_types, 'os_service_types/data'),
		      (os_defaults, 'openstack/config/')],
	       hiddenimports=['novaclient.v2', 'cinderclient.v3',
	                      'keystoneauth1', 'keystoneclient'])

pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          [],
          name='koris',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          runtime_tmpdir=None,
          console=True )

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='koris-dir',
    strip=False,
    upx=True
)
