def test_public_trust_pages_render(client):
    pages = [
        ("/trust", "Trust Center"),
        ("/terms", "Terms and Conditions"),
        ("/privacy", "Privacy Policy"),
        ("/refund-policy", "Refund Policy"),
        ("/provider-agreement", "Provider Agreement"),
        ("/grievance", "Grievance Officer"),
        ("/help", "Help Center"),
        ("/getting-started/seeker", "Seeker Onboarding"),
        ("/getting-started/provider", "Provider Onboarding"),
    ]

    for path, expected in pages:
        response = client.get(path)
        assert response.status_code == 200
        assert expected.encode() in response.data


def test_footer_exposes_policy_links(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Trust center" in response.data
    assert b"Refund policy" in response.data
    assert b"Privacy" in response.data
    assert b"Help center" in response.data
