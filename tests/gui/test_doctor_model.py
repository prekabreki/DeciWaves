"""Qt-free parsing of `deciwaves doctor --json` + the GUI's severity mapping (#68,
spec §3). No importorskip: the Doctor panel's contract is covered on a base install,
so the promotion/neutrality rules can't drift under a no-[gui] CI run."""
from deciwaves.gui.doctor_model import (
    SEV_ERROR,
    SEV_NEUTRAL,
    SEV_OK,
    SEV_WARN,
    DoctorItem,
    load_doctor_payload,
    overall_ok,
    parse_doctor_payload,
    pill_for,
    severity,
)


def _check(name, status, *, ok=None, message="", fix=""):
    # mirrors doctor.Check.as_json(): name/ok/status/message/fix (doctor.py as_json)
    if ok is None:
        ok = status != "broken"
    return {"name": name, "ok": ok, "status": status, "message": message, "fix": fix}


def _payload(ok, checks):
    return {"ok": ok, "checks": checks}


def _item(name, status):
    return DoctorItem(name=name, ok=status != "broken", status=status, message="", fix="")


# --- parse -----------------------------------------------------------------

def test_parse_reads_all_five_json_fields():
    p = _payload(True, [_check("ds_install", "ok", message="DS install: ok", fix="do X")])
    (it,) = parse_doctor_payload(p)
    assert (it.name, it.status, it.ok, it.message, it.fix) == (
        "ds_install", "ok", True, "DS install: ok", "do X")


def test_parse_missing_or_empty_checks_is_empty_list():
    assert parse_doctor_payload({"ok": True, "checks": []}) == []
    assert parse_doctor_payload({}) == []


def test_overall_ok_reflects_payload_flag():
    assert overall_ok(_payload(True, [])) is True
    assert overall_ok(_payload(False, [])) is False
    assert overall_ok({}) is False


# --- severity: the GUI rendering decision (branches on status, not text) ----

def test_broken_is_error_regardless_of_game():
    assert severity(_item("ds_install", "broken"), "ds") == SEV_ERROR
    assert severity(_item("hzd_package", "broken"), "hzd") == SEV_ERROR


def test_not_configured_is_neutral_never_failure():
    # unowned game -> neutral, never red (spec §3)
    assert severity(_item("fw_package", "not_configured"), "fw") == SEV_NEUTRAL
    assert severity(_item("hzd_package", "not_configured"), "ds") == SEV_NEUTRAL


def test_ok_is_ok():
    assert severity(_item("ffmpeg", "ok"), "ds") == SEV_OK


def test_asr_and_cuda_promoted_to_warn_for_hzd_and_fw_when_unavailable():
    # spec §3: the GUI promotes the ASR extra + CUDA to first-class readiness
    # items for the GPU games, even though the CLI keeps them informational.
    assert severity(_item("asr_extra", "unavailable"), "hzd") == SEV_WARN
    assert severity(_item("cuda", "unavailable"), "fw") == SEV_WARN


def test_asr_and_cuda_stay_neutral_for_ds():
    # DS's default chain needs no GPU, so the GPU extras are only informational --
    # neutral whether present or absent, never a green first-class readiness item.
    assert severity(_item("asr_extra", "unavailable"), "ds") == SEV_NEUTRAL
    assert severity(_item("cuda", "unavailable"), "ds") == SEV_NEUTRAL
    assert severity(_item("asr_extra", "ok"), "ds") == SEV_NEUTRAL
    assert severity(_item("cuda", "ok"), "ds") == SEV_NEUTRAL


def test_available_cuda_is_ok_even_for_hzd():
    assert severity(_item("cuda", "ok"), "hzd") == SEV_OK


def test_unrelated_unavailable_check_stays_neutral():
    assert severity(_item("some_tool", "unavailable"), "hzd") == SEV_NEUTRAL


# --- load_doctor_payload: stdout may carry a preamble before the JSON -------

def test_load_parses_clean_json():
    obj = load_doctor_payload('{"ok": true, "checks": []}')
    assert obj == {"ok": True, "checks": []}


def test_load_recovers_json_after_a_stdout_preamble():
    # config.load() prints corruption warnings to stdout, GPU stacks emit import banners
    text = ("warning: config file C:/x/config.json is corrupted; ignoring it\n"
            '{\n  "ok": true,\n  "checks": []\n}\n')
    assert load_doctor_payload(text) == {"ok": True, "checks": []}


def test_load_rejects_unparseable_and_non_object_json():
    assert load_doctor_payload("totally not json") is None
    assert load_doctor_payload("[1, 2, 3]") is None   # valid JSON, not an object
    assert load_doctor_payload("") is None


# --- pill_for: per-game optional/needed pill grading (#112) ------------------


def test_pill_for_cuda_is_optional_on_ds():
    # CUDA absent on DS -> reads as Optional, never a failure (spec §3).
    item = _item("cuda", "unavailable")
    assert pill_for(item, "ds") == ("Optional", "optional")


def test_pill_for_cuda_absent_on_hzd_is_not_optional():
    # On a GPU game CUDA absence is a real readiness gap, not an "Optional" pill.
    item = _item("cuda", "unavailable")
    assert pill_for(item, "hzd") != ("Optional", "optional")


def test_pill_for_broken_required_row_is_needed():
    item = _item("vgmstream", "broken")
    assert pill_for(item, "ds") == ("Needed", "needed")


def test_pill_for_plain_ok_tool_has_no_pill():
    assert pill_for(_item("vgmstream", "ok"), "ds") is None
