from src.bot.constants import KYIV_QUEUES, QUEUES, REGIONS, get_queues_for_region


def test_regions_count():
    assert len(REGIONS) == 4


def test_standard_queues_count():
    assert len(QUEUES) == 12


def test_kyiv_queues_count():
    assert len(KYIV_QUEUES) == 66


def test_get_queues_for_region():
    assert get_queues_for_region("kyiv") == KYIV_QUEUES
    assert get_queues_for_region("kyiv-region") == QUEUES
    assert get_queues_for_region("dnipro") == QUEUES
    assert get_queues_for_region("odesa") == QUEUES
    assert get_queues_for_region("unknown") == QUEUES


def test_region_names():
    assert REGIONS["kyiv"].name == "Київ"
    assert REGIONS["kyiv-region"].name == "Київщина"
    assert REGIONS["dnipro"].name == "Дніпропетровщина"
    assert REGIONS["odesa"].name == "Одещина"
