import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from jinja2.ext import i18n as i18n_ext
from babel.support import Translations

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = str(BASE_DIR / "templates")
LOCALES_DIR = str(BASE_DIR / "locales")

SUPPORTED_LOCALES = ("en", "zh")
DEFAULT_LOCALE = "en"

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    extensions=[i18n_ext],
    autoescape=True,
)

_cache: dict = {}


def get_locale(request) -> str:
    lang = request.cookies.get("lang", "")
    if lang in SUPPORTED_LOCALES:
        return lang
    accept = request.headers.get("accept-language", "")
    if "zh" in accept.lower():
        return "zh"
    return DEFAULT_LOCALE


def _get_translations(locale: str) -> Translations:
    if locale not in _cache:
        _cache[locale] = Translations.load(LOCALES_DIR, [locale])
    return _cache[locale]


def render(request, template_name: str, **kwargs) -> str:
    locale = get_locale(request)
    translations = _get_translations(locale)
    _env.install_gettext_translations(translations)
    template = _env.get_template(template_name)
    return template.render(**kwargs)


def clear_cache():
    _cache.clear()
