from capture_tool.platform.security_software import detect_drm


def test_DRM_01_detects_fasoo_dll_injected_into_our_process():
    found = detect_drm(module_loaded=lambda name: name == "f_nxa.dll", path_exists=lambda p: False)
    assert found == "Fasoo DRM"


def test_DRM_02_detects_fasoo_install_folder():
    found = detect_drm(module_loaded=lambda name: False, path_exists=lambda p: "Fasoo DRM" in str(p))
    assert found == "Fasoo DRM"


def test_DRM_03_nothing_found():
    assert detect_drm(module_loaded=lambda name: False, path_exists=lambda p: False) is None


def test_DRM_04_probe_errors_are_harmless():
    def boom(_):
        raise OSError("access denied")
    assert detect_drm(module_loaded=boom, path_exists=boom) is None


def test_DRM_05_real_probe_runs_on_this_pc():
    assert detect_drm() in (None, "Fasoo DRM", "Softcamp DRM", "MarkAny DRM")
