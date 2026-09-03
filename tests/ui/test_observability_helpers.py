from ui.observability import metric_value_text


def test_metric_value_text_not_instrumented_does_not_render_fake_zero():
    metric = {"status": "NOT_INSTRUMENTED", "value": None, "detail": "Not instrumented"}
    assert metric_value_text(metric) == "Not instrumented"


def test_metric_value_text_formats_ratio_and_ms_values():
    assert metric_value_text({"status": "AVAILABLE", "value": 0.25, "unit": "ratio"}) == "25.0%"
    assert metric_value_text({"status": "AVAILABLE", "value": 12.3456, "unit": "ms"}) == "12.35 ms"
