#!/usr/bin/env python
import os.path as osp
import toml
from orderedset  import OrderedSet
from omegaconf import OmegaConf
from urllib.request import urlretrieve
from xml.etree import ElementTree
import xmltodict
from copy import deepcopy
import git
from pprint import pprint
import click

OmegaConf.register_new_resolver("compiler", lambda x: r'\${{ compiler("%s") }}' % x)

RECIPE_ABOUT = {
    "homepage": "https://www.ros.org/",
    "license": "BSD-3-Clause",
    "summary": "Robot Operating System",
}

RECIPE_TPL_PYTHON = {
    "context": {
        "distro": "???",
        "pkg": "???",
        "group": "???",
    },
    "package": {
        "name": "ros-${context.distro}-${context.pkg}",
        # "name": "ros-\${{distro}}-\${{pkg}}",
        "version": "",
    },
    "source": {},
    "build": {
        "noarch": "python",
        "script": [
            "[ -f $RECIPE_DIR/package.xml ] && cp -f $RECIPE_DIR/package.xml .",
            "python -m pip install . -vv --no-deps --no-build-isolation",
        ]
    },

    "requirements": {
        "host": ['pip'],
        "run": ['python'],
    },

    "tests": [{
        "package_contents": {
            "files": [
                "share/${context.pkg}/package.xml"
            ],
        },
    }],

    "about": deepcopy(RECIPE_ABOUT)
}

RECIPE_TPL_CMAKE = {
    "context": {
        "distro": "???",
        "pkg": "???",
        "group": "???",
    },
    "package": {
        "name": "ros-${context.distro}-${context.pkg}",
        "version": '???',
    },
    "source": {},
    "build": {
        # conda default CFLAGS, CXXFLAGS is bad, so clear it ,using cmake to auto find it instead
        "script": [
            "[ -f $RECIPE_DIR/package.xml ] && cp -f $RECIPE_DIR/package.xml .",
            "mkdir build && cd build",
            "export CFLAGS=",
            "export CXXFLAGS=",
            "cmake .. -DCMAKE_GENERATOR=Ninja \
                -DCMAKE_PREFIX_PATH=$PREFIX \
                -DCMAKE_INSTALL_PREFIX=$PREFIX \
                -DBUILD_TESTING=OFF \
                && ninja install"
        ] ,
    },

    "requirements": {
        "build": ["cmake", "ninja"],
    },

    "tests": [{
        "package_contents": {
            "files": [
                "share/${context.pkg}/package.xml"
            ],
        },
    }],

    "about": deepcopy(RECIPE_ABOUT)
}

def file_name(f):
    return osp.basename(f)

def load_xml(fname):
    tree = ElementTree.parse(fname)
    d = tree.getroot()
    s = ElementTree.tostring(d, encoding='utf-8', method='xml')
    return xmltodict.parse(s)

def is_ros2_pkg(i, distro_dir):
    return osp.isdir(osp.join(distro_dir, i))

def ros2_get_array(pkg, key):
    out = pkg.get(key, [])
    if type(out) == str:
        out = [out]
    return out

def convert_ros2_pkgs(ros2_pkgs, distro, distro_dir):
    return ordered_unique([
        f'ros-{distro}-{i}' if is_ros2_pkg(i, distro_dir) else PKG_MAPPING.get(i, i)
        for i in ros2_pkgs if not (i in PKG_MAPPING and PKG_MAPPING[i] == '')
    ])

PKG_MAPPING = {
    'python3-catkin-pkg-modules': 'catkin_pkg',
    'python3-setuptools': 'pip',
    'python3-importlib-metadata': 'python',
    'python3-importlib-resources': 'python',
    'python3-argcomplete': 'argcomplete',
    'python3': 'python',
    'python3-empy': 'empy',
    'python3-lark-parser': 'lark-parser',
    "google-mock": "gmock",
    "python3-pytest": "pytest",
    "libatomic": "",
}

def add_array_to_dict(dic, key, d):
    if not d:
        return
    a = ordered_unique(list(dic.get(key, [])) + list(d))
    dic[key] = a

def ros2_grab_export_depends(seeds, key, distro_dir):
    if not seeds:
        return []

    queue = [i for i in seeds if is_ros2_pkg(i, distro_dir)]
    new_seeds = []
    for i in queue:
        export_f = osp.join(distro_dir, i, 'export.yaml')
        assert osp.exists(export_f)
        new_seeds += OmegaConf.load(export_f)[key]

    return ordered_unique(seeds.copy() + ros2_grab_export_depends(new_seeds, key, distro_dir))

GBP_GIT_URL = "https://github.com/ros2-gbp/{group}-release"
GBP_GIT_REV = "release/{distro}/{pkg}/{gbp_tag}"

def get_git_raw_url(url):
    if 'github.com' in url:
        return url.replace("https://github.com", "https://raw.githubusercontent.com")
    else:
        raise

git_cmd = git.cmd.Git()
def gbp_get_tag(repo_url, pattern):
    gbp_tag = sorted([i for i in git_cmd.ls_remote("--tags", repo_url).split('\n') if pattern in i])[-1].split('/')[-1]
    return gbp_tag

def ordered_unique(a):
    return list(OrderedSet(a))

def ordered_union(a, b):
    return ordered_unique(list(a) + list(b))

def add_dict_to_array(a, dic, key):
    if b := dic.get(key, []):
        return ordered_union(a, b)
    else:
        return ordered_unique(a)

@click.command()
@click.option('--distro', '-d', type=click.Choice(['humble', 'rolling', 'auto'], case_sensitive=False), default='auto')
@click.option('--repo_type', '-r', type=click.Choice(['single', 'collection', 'gbp'], case_sensitive=False), default='gbp')
@click.option('--build_num', '-n', default=1)
@click.option('--dry-run', '-t', default=False)
@click.argument('src')
def main(distro, repo_type, build_num, dry_run, src):
    assert osp.isdir(src)
    src = src.rstrip('/')
    distro_dir = osp.dirname(src)
    if distro == 'auto':
        distro = osp.basename(distro_dir)

    pkg = file_name(src)

    cfg = OmegaConf.create({
        'group': pkg,

        'repo_type': repo_type,
        'source': {},
        'build': {
            "number": build_num,
        },
        'requirements': {},
    })

    cfg_f = osp.join(src, 'config.toml')
    if osp.exists(cfg_f):
        cfg = OmegaConf.merge(cfg, toml.load(cfg_f))

    if cfg.repo_type == 'gbp':
        if not cfg.source.get('git_url', ''):
            cfg.source.git_url = GBP_GIT_URL
        git_url = cfg.source.git_url.format(group=cfg.group)
        gbp_tag = gbp_get_tag(git_url, GBP_GIT_REV.format(distro=distro, pkg=pkg, gbp_tag=''))
        git_rev = GBP_GIT_REV.format(distro=distro, pkg=pkg, gbp_tag=gbp_tag)
    elif cfg.repo_type == 'single':
        raise
    elif cfg.repo_type == 'collection':
        raise

    git_raw_url = get_git_raw_url(git_url)

    repo_pkg_xml_f = osp.join(src, 'repo_package.xml')
    if not osp.exists(repo_pkg_xml_f) or load_xml(repo_pkg_xml_f)['package']['name'] != pkg:
        url = osp.join(git_raw_url, git_rev, 'package.xml')
        print (f"request {url}")
        urlretrieve(url, repo_pkg_xml_f)

    pkg_xml_f = repo_pkg_xml_f
    if osp.exists(p := osp.join(src, 'package.xml')):
        pkg_info = load_xml(p)['package']
        repo_pkg_info = load_xml(repo_pkg_xml_f)['package']
        assert pkg_info['name'] == repo_pkg_info['name'] and pkg_info['version'] == repo_pkg_info['version'], \
            f"({pkg_info["name"]}, {pkg_info["version"]}) != ({repo_pkg_info["name"]}, {repo_pkg_info["version"]})"
        pkg_xml_f = p

    ros2_pkg = OmegaConf.create(load_xml(pkg_xml_f)).package
    if cfg.repo_type == 'gbp':
        assert ros2_pkg.version in git_rev, f"{ros2_pkg.version} not in {git_rev}"

    build_type = ros2_pkg.export.build_type

    buildtool_depends = ros2_get_array(ros2_pkg, 'buildtool_depend')
    buildtool_depends = add_dict_to_array(buildtool_depends, cfg, 'buildtool_depends')
    buildtool_depends = ros2_grab_export_depends(buildtool_depends, 'buildtool', distro_dir)

    depends = ros2_get_array(ros2_pkg, "depend")
    build_depends = ros2_get_array(ros2_pkg, 'build_depend') + depends
    build_depends = add_dict_to_array(build_depends, cfg, 'build_depends')
    build_depends = ros2_grab_export_depends(build_depends, 'build', distro_dir)

    exec_depends = ros2_get_array(ros2_pkg, 'exec_depend') + depends

    if build_type == 'ament_python':
        recipe = OmegaConf.create(RECIPE_TPL_PYTHON)
    elif build_type in ('ament_cmake', 'cmake'):
        recipe = OmegaConf.create(RECIPE_TPL_CMAKE)
    else:
        raise

    recipe.context.update({
        'distro': distro,
        'pkg': pkg,
        'group': cfg.group,
    })

    req = recipe.requirements
    add_array_to_dict(req, 'build', convert_ros2_pkgs(buildtool_depends, distro, distro_dir))
    add_array_to_dict(req, 'host', convert_ros2_pkgs(build_depends, distro, distro_dir))
    add_array_to_dict(req, 'run', convert_ros2_pkgs(exec_depends, distro, distro_dir))

    recipe.package.version = ros2_pkg.version
    recipe.source.update({
        'git': git_url,
        'rev': git_rev,
    })
    OmegaConf.update(recipe, 'build', cfg.build) # for dict deep merge
    OmegaConf.update(recipe, 'requirements', cfg.requirements)
    recipe.about.update({
        # 'license': ros2_pkg.license,
        'description': ros2_pkg.description,
    })

    recipe_str = OmegaConf.to_yaml(recipe, resolve=True)

    print (recipe_str)

    print ("exporting ...")
    buildtool_export_depends = ros2_get_array(ros2_pkg, 'buildtool_export_depend') + depends
    buildtool_export_depends = add_dict_to_array(buildtool_export_depends, cfg, 'buildtool_export_depends')

    build_export_depends = ros2_get_array(ros2_pkg, 'build_export_depend')
    build_export_depends = add_dict_to_array(build_export_depends, cfg, 'build_export_depends')

    export = {
        "buildtool": buildtool_export_depends,
        "build": build_export_depends,
    }
    export_str = OmegaConf.to_yaml(export)
    print (export_str)

    if not dry_run:
        out_f = osp.join(src, 'recipe.yaml')
        open(out_f, 'w').write(recipe_str)

        out_f = osp.join(src, 'export.yaml')
        open(out_f, 'w').write(export_str)

if __name__ == "__main__":
    main()
