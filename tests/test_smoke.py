from merchantops.demo.smoke import run_smoke


async def test_demo_smoke_checks_story_and_error_strings():
    result = await run_smoke()
    assert result["gst"]["tax_total"] == "1812.15"
    assert result["customer_email"] == "r***@example.com"
    assert result["missing"]["error"]["code"] == "not_found"
    assert result["bad_date"]["error"]["message"] == "date_from must be an ISO date (YYYY-MM-DD)."
    assert result["refused"]["executed"] is False
    assert "reconcile_orders" in result["tools"]
    assert len(result["tools"]) == 21
