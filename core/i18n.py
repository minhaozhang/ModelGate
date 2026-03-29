import logging
from io import BytesIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from jinja2.ext import i18n as i18n_ext
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po
from babel.support import NullTranslations, Translations

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
_logger = logging.getLogger(__name__)


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
        try:
            _cache[locale] = Translations.load(LOCALES_DIR, [locale])
        except UnicodeDecodeError:
            _logger.warning("Failed to load %s .mo translations, falling back to .po", locale)
            _cache[locale] = _load_translations_from_po(locale)
        except Exception:
            if locale != DEFAULT_LOCALE:
                _logger.exception(
                    "Failed to load %s translations, falling back to %s",
                    locale,
                    DEFAULT_LOCALE,
                )
                _cache[locale] = _get_translations(DEFAULT_LOCALE)
            else:
                _logger.exception("Failed to load default translations, using null translations")
                _cache[locale] = NullTranslations()
    return _cache[locale]


def _load_translations_from_po(locale: str) -> Translations:
    po_path = BASE_DIR / "locales" / locale / "LC_MESSAGES" / "messages.po"
    if not po_path.exists():
        if locale != DEFAULT_LOCALE:
            return _get_translations(DEFAULT_LOCALE)
        return NullTranslations()

    try:
        with po_path.open("r", encoding="utf-8") as fp:
            catalog = read_po(fp, locale=locale)
        mo_buffer = BytesIO()
        write_mo(mo_buffer, catalog)
        mo_buffer.seek(0)
        return Translations(fp=mo_buffer)
    except Exception:
        if locale != DEFAULT_LOCALE:
            _logger.exception(
                "Failed to load %s .po translations, falling back to %s",
                locale,
                DEFAULT_LOCALE,
            )
            return _get_translations(DEFAULT_LOCALE)
        _logger.exception("Failed to load default .po translations, using null translations")
        return NullTranslations()


def render(request, template_name: str, **kwargs) -> str:
    locale = get_locale(request)
    translations = _get_translations(locale)
    template = _env.get_template(template_name)
    context = {
        "_": translations.gettext,
        "gettext": translations.gettext,
        "ngettext": translations.ngettext,
        **kwargs,
    }
    return template.render(**context)


def clear_cache():
    _cache.clear()
