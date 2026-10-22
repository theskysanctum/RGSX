"""Games > Add a System: re-adds one of the EmulationStation systems the curated Panthera build
leaves out of its default es_systems.cfg (see PANTHERA_SHOP_INSTALL_TARGET_CMDS in
panthera-shop.mk) - no default/preinstalled content, just the <system> entry itself, same as
EmulationStation would ship it.

es_systems_removed.cfg is generated at build time by the exact same tool, from the exact same
schema, as the real es_systems.cfg - just pointed at the systems the curation left out, with an
empty --roms-dir so nothing bundled ever ships through this. This module never re-derives any of
that; it only reads the <system> blocks that tool already produced and splices the chosen one
into userdata, so EmulationStation picks it up on its own.
"""
import logging
import os
import xml.dom.minidom
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

REMOVED_SYSTEMS_CFG = "/usr/share/batocera/panthera-shop/es_systems_removed.cfg"
ES_CONFIG_DIR = "/userdata/system/configs/emulationstation"
ES_SYSTEMS_CUSTOM = os.path.join(ES_CONFIG_DIR, "es_systems_custom.cfg")
ES_SYSTEMS_USERDATA = os.path.join(ES_CONFIG_DIR, "es_systems.cfg")
ES_SYSTEMS_BAKED = "/usr/share/emulationstation/es_systems.cfg"


def _parse_system_list(path):
    """Returns the <systemList> root, or None if the file is missing, unreadable or not one."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as e:
        logger.debug(f"Could not parse {path}: {e}")
        return None
    return root if root.tag == "systemList" else None


def load_removed_systems():
    """Every system this build doesn't ship by default, sorted by display name. Never raises -
    an older build without es_systems_removed.cfg, or one where generating it failed, just means
    an empty list here rather than a broken screen."""
    root = _parse_system_list(REMOVED_SYSTEMS_CFG)
    if root is None:
        return []

    entries = []
    for system in root.findall("system"):
        name = (system.findtext("name") or "").strip()
        if not name:
            continue
        fullname = (system.findtext("fullname") or name).strip() or name
        manufacturer = (system.findtext("manufacturer") or "").strip()
        entries.append({"name": name, "fullname": fullname, "manufacturer": manufacturer})

    entries.sort(key=lambda entry: entry["fullname"].lower())
    return entries


def _active_systems_path():
    """Mirrors EmulationStation's own SystemData::getConfigPath(): whichever of these it finds
    first at startup is the systems file it actually uses, in full - never merged with the
    others. es_systems_custom.cfg (ours, if we've ever written one) always wins."""
    for path in (ES_SYSTEMS_CUSTOM, ES_SYSTEMS_USERDATA, ES_SYSTEMS_BAKED):
        if os.path.exists(path):
            return path
    return None


def is_system_active(system_name):
    """True if `system_name` is already in whichever es_systems file EmulationStation currently
    reads - either added back already, or never removed from this build in the first place."""
    path = _active_systems_path()
    root = _parse_system_list(path) if path else None
    if root is None:
        return False
    return any((system.findtext("name") or "").strip() == system_name for system in root.findall("system"))


def add_system(system_name):
    """Splices `system_name`'s <system> block into es_systems_custom.cfg, starting from whatever
    EmulationStation currently reads (not always es_systems_custom.cfg itself) so nothing already
    active is lost - safe to call again for another system before the next EmulationStation
    restart. Returns "added", "already_active", or "not_found"; never raises, since a failure
    here should just mean nothing happened rather than take the app down.
    """
    try:
        removed_root = _parse_system_list(REMOVED_SYSTEMS_CFG)
        if removed_root is None:
            return "not_found"

        new_system = next(
            (s for s in removed_root.findall("system") if (s.findtext("name") or "").strip() == system_name),
            None,
        )
        if new_system is None:
            return "not_found"

        base_path = _active_systems_path()
        root = _parse_system_list(base_path) if base_path else None
        if root is None:
            root = ET.Element("systemList")

        if any((s.findtext("name") or "").strip() == system_name for s in root.findall("system")):
            return "already_active"

        root.append(new_system)

        os.makedirs(ES_CONFIG_DIR, exist_ok=True)
        rough_string = '<?xml version="1.0"?>\n' + ET.tostring(root, encoding='unicode')
        pretty_xml = xml.dom.minidom.parseString(rough_string).toprettyxml(indent="\t", encoding='utf-8').decode('utf-8')
        pretty_xml = '\n'.join(line for line in pretty_xml.split('\n') if line.strip())
        with open(ES_SYSTEMS_CUSTOM, 'w', encoding='utf-8') as f:
            f.write(pretty_xml)
        try:
            os.chmod(ES_SYSTEMS_CUSTOM, 0o644)
        except OSError as e:
            # exFAT (dArkOS ROM card) cannot store permissions; the file is already written.
            logger.debug(f"chmod skipped for {ES_SYSTEMS_CUSTOM}: {e}")

        logger.info(f"Added system '{system_name}' to {ES_SYSTEMS_CUSTOM}")
        return "added"
    except Exception as e:
        logger.error(f"Error adding system '{system_name}': {e}")
        return "not_found"
