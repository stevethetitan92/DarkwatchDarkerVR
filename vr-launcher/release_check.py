"""Read public release metadata; never download or change an installation."""
import json
import http.client
import re
import urllib.error
import urllib.request

REPOSITORY = 'https://github.com/linkssy2/DarkwatchDarkerEdition'
API_URL = 'https://api.github.com/repos/linkssy2/DarkwatchDarkerEdition/releases?per_page=30'
VR_REPOSITORY = 'https://github.com/stevethetitan92/DarkwatchDarkerVR'
VR_API_URL = 'https://api.github.com/repos/stevethetitan92/DarkwatchDarkerVR/releases?per_page=30'
TIMEOUT = 5
MAX_BYTES = 2 * 1024 * 1024
SUFFIX = {'windows': 'Windows-x64.zip', 'linux': 'Linux-Proton-Experimental.tar.gz'}


def version(text):
    match = re.fullmatch(r'[vV]?([0-9]{1,4})\.([0-9]{1,4})(?:\.([0-9]{1,4}))?', text) if isinstance(text, str) else None
    return tuple(int(value or 0) for value in match.groups()) if match else None


def format_message(result, language='en'):
    spanish = language == 'es'
    if result['status'] == 'available':
        latest = result['latest_version']
        return (f'Darkwatch {latest} está disponible en GitHub.' if spanish else
                f'Darkwatch {latest} is available on GitHub.')
    if result['status'] == 'current':
        return ('No hay una versión más reciente para esta plataforma.' if spanish else
                'No newer release is available for this platform.')
    return ('No se pudieron comprobar las actualizaciones. Puedes seguir jugando.' if spanish else
            'Could not check for updates. You can keep playing.')


def result(status, current, platform, **fields):
    value = dict(status=status, current_version=current, platform=platform, **fields)
    value['message'] = format_message(value)
    return value


def select_release(releases, current_version, platform):
    current = version(current_version)
    if current is None or platform not in SUFFIX or not isinstance(releases, list):
        return result('unavailable', current_version, platform)
    choices = []
    for release in releases:
        if (not isinstance(release, dict) or release.get('draft') is not False or
                release.get('prerelease') is not False or not isinstance(release.get('published_at'), str) or
                not release['published_at']):
            continue
        tag = release.get('tag_name')
        number = version(tag)
        if number is None or not tag.startswith('v'):
            continue
        page = REPOSITORY + '/releases/tag/' + tag
        if release.get('html_url') != page:
            continue
        name = 'Darkwatch-Darker-Edition-' + tag.lstrip('vV') + '-' + SUFFIX[platform]
        download = REPOSITORY + '/releases/download/' + tag + '/' + name
        assets = release.get('assets')
        matched = next((asset for asset in assets if
                isinstance(asset, dict) and asset.get('name') == name and
                asset.get('state') == 'uploaded' and type(asset.get('size')) is int and asset['size'] > 0 and
                asset.get('browser_download_url') == download), None) if isinstance(assets, list) else None
        if matched is None:
            continue
        choices.append((number, tag.lstrip('vV'), page, matched))
    if not choices:
        return result('unavailable', current_version, platform)
    number, latest, page, asset = max(choices, key=lambda item: item[0])
    if number > current:
        return result('available', current_version, platform, latest_version=latest, release_url=page,
                      asset_name=asset['name'], asset_url=asset['browser_download_url'],
                      asset_size=asset['size'], asset_digest=asset.get('digest'))
    return result('current', current_version, platform, latest_version=latest)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def vr_version(text):
    match = re.fullmatch(r'([0-9]{1,4}\.[0-9]{1,4}(?:\.[0-9]{1,4})?)(?:-vr([0-9]{1,4}))?', text or '')
    return (*version(match[1]), int(match[2] or 0)) if match else None


def select_vr_release(releases, current_version, platform):
    current = vr_version(current_version)
    if current is None or not isinstance(releases, list):
        return result('unavailable', current_version, platform)
    choices = []
    for release in releases:
        if not isinstance(release, dict) or release.get('draft') is not False or release.get('prerelease') is not False:
            continue
        if not isinstance(release.get('published_at'), str) or not release['published_at']:
            continue
        tag = release.get('tag_name')
        if not isinstance(tag, str) or not tag.startswith('v'):
            continue
        label = tag[1:]
        number = vr_version(label)
        page = VR_REPOSITORY + '/releases/tag/' + tag
        if number is not None and release.get('html_url') == page:
            choices.append((number, label, page))
    if choices:
        number, latest, page = max(choices)
        if number > current:
            return result('available', current_version, platform, latest_version=latest, release_url=page)
    return result('current', current_version, platform)


def check(current_version, platform='windows', *, vr=False):
    parse_version = vr_version if vr else version
    if parse_version(current_version) is None or platform not in SUFFIX:
        return result('unavailable', current_version, platform)
    request = urllib.request.Request(VR_API_URL if vr else API_URL, headers={
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'Darkwatch-Darker-Edition/' + current_version,
        'X-GitHub-Api-Version': '2022-11-28',
    })
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=TIMEOUT) as response:
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('Release response exceeds the size limit')
        select = select_vr_release if vr else select_release
        return select(json.loads(data.decode('utf-8')), current_version, platform)
    except (OSError, ValueError, http.client.HTTPException, RecursionError):
        return result('unavailable', current_version, platform)
