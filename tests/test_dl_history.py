"""The permanent record of finished downloads."""

from siphon.core import dl_history
from siphon.core.dl_history import DownloadHistory, norm_name, norm_url


def test_the_same_video_has_one_key_however_the_address_is_written():
    key = norm_url('https://www.site.test/video/12/')
    assert key == norm_url('http://site.test/video/12')
    assert key == norm_url('https://site.test/video/12?utm_source=mail&x=1')


def test_a_video_id_in_the_query_is_part_of_the_identity():
    assert norm_url('https://site.test/watch?v=a') != norm_url('https://site.test/watch?v=b')


def test_a_file_name_matches_with_or_without_its_extension_and_case():
    assert norm_name('My  Clip.MP4') == norm_name('my clip')
    assert norm_name('') == ''
    assert norm_name(None) == ''


def test_a_finished_download_is_found_again_after_a_restart(tmp_path):
    path = str(tmp_path / 'history.json')
    history = DownloadHistory(path)
    history.add('https://site.test/v/1', 'Clip One.mp4', size=100)
    again = DownloadHistory(path)
    assert len(again) == 1
    assert again.match_url('https://www.site.test/v/1/')['name'] == 'Clip One.mp4'


def test_the_same_name_from_another_address_is_a_duplicate_but_not_itself(tmp_path):
    history = DownloadHistory(str(tmp_path / 'h.json'))
    history.add('https://site.test/v/1', 'Clip One.mp4')
    assert history.match_name('clip one', 'https://other.test/x') is not None
    assert history.match_name('clip one', 'https://site.test/v/1') is None
    assert history.match_name('', '') is None


def test_removing_a_download_forgets_its_name_too(tmp_path):
    path = str(tmp_path / 'h.json')
    history = DownloadHistory(path)
    history.add('https://site.test/v/1', 'Clip One.mp4')
    assert history.remove('https://site.test/v/1')['name'] == 'Clip One.mp4'
    assert history.match_name('clip one') is None
    assert len(DownloadHistory(path)) == 0
    assert history.remove('https://site.test/never') is None


def test_the_average_size_uses_the_recent_ones_that_have_a_size(tmp_path):
    history = DownloadHistory(str(tmp_path / 'h.json'))
    assert history.average_size() == 0
    history.add('https://s.test/1', 'a', size=100, at=1)
    history.add('https://s.test/2', 'b', at=2)            # no size known
    history.add('https://s.test/3', 'c', size=300, at=3)
    assert history.average_size() == 200
    assert history.average_size(last=1) == 300


def test_importing_old_entries_skips_the_ones_already_known(tmp_path):
    history = DownloadHistory(str(tmp_path / 'h.json'))
    history.add('https://s.test/1', 'a')
    added = history.add_many([('https://s.test/1', 'a', 1),
                              ('https://s.test/2', 'b', 2),
                              ('', 'blank', 3)])
    assert added == 1 and len(history) == 2


def test_a_damaged_history_file_starts_empty_instead_of_crashing(tmp_path):
    path = tmp_path / 'h.json'
    path.write_text('{this is not json', encoding='utf-8')
    assert len(DownloadHistory(str(path))) == 0


def test_describe_names_the_file_and_the_time():
    entry = {'url': 'https://s.test/1', 'name': 'Clip', 'at': 0}
    assert '"Clip"' in dl_history.describe(entry)
    assert dl_history.describe(None) == ''
