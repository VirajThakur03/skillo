from app.extensions import db
from app.models import Message, Skill


def test_skill_inquiry_rooms_are_isolated_per_seeker(
    app,
    client,
    register_user,
    auth_headers,
):
    provider, provider_token = register_user(
        "provider",
        name="Inquiry Provider",
        email="inquiry-provider@example.com",
    )
    seeker_one, seeker_one_token = register_user(
        "seeker",
        name="Inquiry Seeker One",
        email="inquiry-seeker-one@example.com",
    )
    seeker_two, seeker_two_token = register_user(
        "seeker",
        name="Inquiry Seeker Two",
        email="inquiry-seeker-two@example.com",
    )

    with app.app_context():
        skill = Skill(
            provider_id=provider["id"],
            title="Painter",
            description="Interior painting",
            price=900,
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.commit()
        skill_id = skill.id

    room_one = f"skill_{skill_id}_{seeker_one['id']}"
    room_two = f"skill_{skill_id}_{seeker_two['id']}"

    response_one = client.post(
        f"/api/chat/room/{room_one}",
        headers=auth_headers(seeker_one_token),
        json={"content": "Can you come tomorrow morning?"},
    )
    assert response_one.status_code == 201

    response_two = client.post(
        f"/api/chat/room/{room_two}",
        headers=auth_headers(seeker_two_token),
        json={"content": "Do you bring your own materials?"},
    )
    assert response_two.status_code == 201

    seeker_one_history = client.get(
        f"/api/chat/room/{room_one}",
        headers=auth_headers(seeker_one_token),
    )
    assert seeker_one_history.status_code == 200
    assert [item["content"] for item in seeker_one_history.get_json()] == [
        "Can you come tomorrow morning?"
    ]

    seeker_two_blocked = client.get(
        f"/api/chat/room/{room_one}",
        headers=auth_headers(seeker_two_token),
    )
    assert seeker_two_blocked.status_code == 403

    provider_rooms = client.get(
        "/api/chat/rooms",
        headers=auth_headers(provider_token),
    )
    assert provider_rooms.status_code == 200
    rooms = provider_rooms.get_json()["items"]
    assert {item["room"] for item in rooms if item["room"].startswith("skill_")} == {
        room_one,
        room_two,
    }

    with app.app_context():
        stored_messages = Message.query.filter(Message.room.in_([room_one, room_two])).all()
        assert len(stored_messages) == 2
