"""Kural önerilerinden eklenen check'ler (sentetik Analysis taklidi; müşteri verisi yok)."""
from collections import Counter
from types import SimpleNamespace as NS

from pcs7_analyzer.checks import ACTIONS, CHECKS, get_check
from pcs7_analyzer.model import Confidence

NEW_IDS = ["HW_CPU_PRE_0499", "HW_CPU_EXT_DRIVER_FW", "HW_CPU_INT_PN", "HW_ET200SP_IM", "HW_UNSUPPORTED_CP", "HW_DIAG_REPEATER",
           "HW_AS_RTX", "HW_CPU410_FW_TCIR", "HW_CPU_RT_SFC78", "HW_APL_S7400_ONLY", "HW_FF_AB7000", "HW_DISCONTINUED",
           "LIB_APL_MULTI_AS", "LIB_RESERVED_NUMBERS", "LIB_LEGACY_AUTHOR", "BLK_PA_CPU_MANUAL"]


def st(name="AS01", inv=None, cpus=(), text="", project="P1", gsd=None):
    return NS(name=name, source="x.cfg", project=project, inventory=Counter(inv or {}), cpus=list(cpus), station_text=text,
              gsd=Counter(gsd or {}))


def bf(label="AS01", project="P1", **kw):
    d = dict(as_label=label, info=NS(project=project, dbf="ombstx/offline/0001/SUBBLK.DBF"), block_names=[], fb_library={},
             code_len={}, features=[], libraries={}, counts={"FB": 1})
    d.update(kw)
    return NS(**d)


def an_(stations=(), folders=(), matches=(), os=()):
    return NS(stations=list(stations), as_folders=list(folders), block_folders=list(folders), hw_matches=list(matches),
              released_list="released.csv", os_projects=list(os))


def run(cid, an):
    c = get_check(cid)
    return c.func(c, an)


def test_all_new_checks_registered_with_action():
    ids = {c.id for c in CHECKS}
    assert set(NEW_IDS) <= ids and len(ids) == len(CHECKS)
    for i in NEW_IDS:
        assert ACTIONS[i][0] and ACTIONS[i][1]
        assert get_check(i).manual_ref != "-"


def test_empty_analysis_no_crash():
    for i in NEW_IDS:
        assert run(i, an_()) == []


def test_diag_repeater_and_int_pn_and_et200sp():
    a = an_([st(inv={("6ES7 972-0AB00-0XA0", ""): 2, ("6ES7 414-3EM05-0AB0", "V5.1"): 1,
                     ("6ES7 134-6TD00-0CA1", ""): 1, ("6ES7 134-6PA00-0BD0", ""): 1})])
    f = run("HW_DIAG_REPEATER", a)
    assert len(f) == 1 and f[0].confidence == Confidence.HIGH
    assert run("HW_CPU_INT_PN", a)[0].confidence == Confidence.LOW
    assert len(run("HW_ET200SP_IM", a)) == 2


def test_cpu_notes_21_14_and_21_12():
    m1 = NS(kind="modül", note="21.14 CPU prior to 04/99", order="6ES7 414-2XJ00-0AB0", fw="", count=1, stations=["AS01"],
            discontinued="04/98")
    m2 = NS(kind="modül", note="21.12 H-CPU as of 04/99", order="6ES7 414-4HJ00-0AB0", fw="V2.1.1", count=1, stations=["AS01"],
            discontinued="")
    m3 = NS(kind="modül", note="21.12 H-CPU as of 04/99", order="6ES7 417-4HL01-0AB0", fw="V3.1", count=1, stations=["AS02"],
            discontinued="")
    a = an_(matches=[m1, m2, m3])
    assert "6ES7 414-2XJ00-0AB0" in run("HW_CPU_PRE_0499", a)[0].detail
    d = run("HW_CPU_EXT_DRIVER_FW", a)[0].detail
    assert "414-4HJ00" in d and "417-4HL01" not in d
    assert len(run("HW_DISCONTINUED", a)) == 1


def test_cpu410_fw_tcir():
    a = an_([st(cpus=[("6ES7 410-5HX08-0AB0", "V8.1", "CPU 410-5H"), ("6ES7 410-5HX08-0AB0", "", "CPU 410-5H")])])
    f = run("HW_CPU410_FW_TCIR", a)
    assert len(f) == 2 and f[1].confidence == Confidence.LOW
    ok = an_([st(cpus=[("6ES7 410-5HX08-0AB0", "V8.2.3", "")])])
    assert run("HW_CPU410_FW_TCIR", ok) == []


def test_rtx_split_box_vs_as():
    from pcs7_analyzer.checks import box_rtx
    box = an_([st(text="SIMATIC PCS 7 BOX RTX WinAC RTX")])
    assert box_rtx(get_check("HW_BOX_RTX"), box)[0].blocking
    assert run("HW_AS_RTX", box) == []
    asr = an_([st(text="PC station WinLC RTX V4.0")])
    assert box_rtx(get_check("HW_BOX_RTX"), asr) == []
    f = run("HW_AS_RTX", asr)[0]
    assert not f.blocking and f.confidence == Confidence.LOW


def test_unsupported_cp_ff_apl_s7400():
    a = an_([st(text="CP 1613 A2 ; Profibus AB7000", cpus=[("6ES7 517-3FP00-0AB0", "V2.9", "")])],
            [bf(features=["APL"])])
    assert "CP 1613" in run("HW_UNSUPPORTED_CP", a)[0].detail
    assert run("HW_FF_AB7000", a)
    assert run("HW_APL_S7400_ONLY", a)[0].confidence == Confidence.LOW


def test_cpu_rt_sfc78():
    f = bf(block_names=["CPU_RT"])
    a = an_([st(cpus=[("6ES7 414-4HJ00-0AB0", "V4.0", "")])], [f])
    assert run("HW_CPU_RT_SFC78", a)
    a2 = an_([st(cpus=[("6ES7 416-3XR05-0AB0", "V5.2", "")])], [f])
    assert run("HW_CPU_RT_SFC78", a2) == []


def test_reserved_numbers_and_pa_cpu_and_legacy():
    custom = bf(fb_library={245: ("MYFB", "custom", "BM"), 246: ("SFC_X", "SFC system", "ES_SFC")}, block_names=["PA_CPU"],
                code_len={"FC245": 100}, libraries={"custom": {"BM": 1}, "Basis Library": {"DRIVER60": 3}})
    a = an_(folders=[custom])
    f = run("LIB_RESERVED_NUMBERS", a)
    assert any("FB245" in x.detail and "FB246" not in x.detail for x in f)
    assert any(x.confidence == Confidence.LOW and "FC245" in x.detail for x in f)
    assert run("BLK_PA_CPU_MANUAL", a)
    assert "DRIVER60" in run("LIB_LEGACY_AUTHOR", a)[0].detail
    sfc_ok = bf(fb_library={300: ("SFC", "SFC system", "ES_SFC")}, features=["SFC"], code_len={"FC245": 1})
    assert run("LIB_RESERVED_NUMBERS", an_(folders=[sfc_ok])) == []


def test_apl_multi_as():
    f1 = bf("AS01", libraries={"APL": {"AdvLib81": 5}})
    f2 = bf("AS02", project="P2", libraries={"APL": {"AdvLib82": 5}})
    a = an_(folders=[f1, f2], os=[NS(), NS()])
    a.target = "V10.0SP2"
    out = run("LIB_APL_MULTI_AS", a)
    assert out and out[0].confidence == Confidence.LOW
    assert run("LIB_APL_MULTI_AS", an_(folders=[f1, f2])) == []     # OS yok -> sessiz


def test_extra_coverage_rows_and_roadmap_p0(tmp_path):
    from pcs7_analyzer.analyze import analyze
    from pcs7_analyzer.demo import build_demo_project
    from pcs7_analyzer.readiness import backup_coverage
    from pcs7_analyzer.roadmap import build_roadmap
    an = analyze(build_demo_project(tmp_path))
    cov = {r[0]: r for r in backup_coverage(an)}
    keys = [k for k in cov if k.startswith(("F-System parametreleri", "Process Historian", "PC station envanteri", "ES yazılım",
                                            "Time synchronization", "Archive SQL", "Lifebeat", "ES compile"))]
    assert len(keys) == 8 and all(cov[k][1] in ("VERİ YOK", "Kısmen") for k in keys)
    p0 = next(p for p in build_roadmap(an) if p.id == "P0")
    titles = " ".join(s.title for s in p0.steps)
    assert "Process Historian" in titles and "F-System parametreleri" in titles
