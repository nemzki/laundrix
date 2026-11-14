"""Own-profile writes and private, bounded image storage using the existing account gate."""
import io
import re
import pytest
from PIL import Image, PngImagePlugin
from app.extensions import db
from app.models import AccountStatus
from app.auth.services import authorize_google_user
from app.core import profile_avatars


@pytest.fixture(autouse=True)
def isolated_avatars(app, tmp_path):
    app.config['PROFILE_AVATAR_DIR'] = str(tmp_path / 'avatars')


def image_bytes(format='PNG', size=(64,64)):
    stream = io.BytesIO()
    image = Image.new('RGB', size, '#3478f6')
    metadata = PngImagePlugin.PngInfo(); metadata.add_text('private_note', 'do-not-retain')
    image.save(stream, format=format, **({'pnginfo': metadata} if format == 'PNG' else {}))
    return stream.getvalue()


def post(client, name=' Updated Name ', image=None, filename='photo.png', **extra):
    data = {'full_name': name, **extra}
    if image is not None:
        data['profile_picture'] = (io.BytesIO(image), filename)
    return client.post('/settings/profile', data=data, content_type='multipart/form-data')


@pytest.mark.parametrize('role', ['admin','staff'])
def test_own_profile_persists_and_sidebar_and_dashboard_share_it(request, role):
    client = request.getfixturevalue(f'{role}_client'); user = request.getfixturevalue(role)
    assert post(client, image=image_bytes()).status_code == 303
    db.session.refresh(user)
    assert user.full_name == 'Updated Name'
    assert re.fullmatch(r'/settings/avatar/avatar-[a-f0-9]{32}\.png', user.picture_url)
    for route in ('/settings','/orders/', '/dashboard/'):
        html = client.get(route).get_data(as_text=True)
        assert 'Updated Name' in html and user.picture_url in html
    response = client.get(user.picture_url)
    assert response.status_code == 200 and response.mimetype == 'image/png'
    assert response.headers['Cache-Control'] == 'private, no-store'
    image = Image.open(io.BytesIO(response.data))
    assert image.size == (512,512) and image.info == {}
    assert b'do-not-retain' not in response.data
    assert client.get('/settings').get_data(as_text=True).count('Personal Settings | Laundrix') == 1


@pytest.mark.parametrize('name', ['', '   ', 'A', 'x'*151, 'A\x00B'])
def test_invalid_names_do_not_write(admin_client, admin, name):
    before = admin.full_name
    assert post(admin_client, name=name, image=image_bytes()).status_code == 422
    db.session.refresh(admin); assert admin.full_name == before
    assert not list(profile_avatars.directory().glob('*'))


# Short explicit ids: pytest would otherwise build the id from the 1 MB payload, and on Windows
# pytest stores the id in an environment variable, which is limited to 32,767 characters.
@pytest.mark.parametrize('data,filename', [
    pytest.param(b'<svg onload=alert(1) />', 'photo.png', id='svg-markup-as-png'),
    pytest.param(b'not an image', 'photo.jpg', id='not-an-image'),
    pytest.param(image_bytes(), 'photo.svg', id='svg-extension'),
    pytest.param(image_bytes(), 'photo.jpg', id='png-bytes-as-jpg'),
    pytest.param(b'', 'photo.png', id='empty-file'),
    pytest.param(b'x'*(1024*1024+1), 'photo.png', id='over-1mb'),
    pytest.param(image_bytes(size=(20,20)), 'tiny.png', id='too-small'),
    pytest.param(image_bytes(size=(2049,32)), 'huge.png', id='too-wide'),
])
def test_invalid_images_do_not_change_profile(admin_client, admin, data, filename):
    before = (admin.full_name, admin.picture_url)
    assert post(admin_client, image=data, filename=filename).status_code == 422
    db.session.refresh(admin); assert (admin.full_name, admin.picture_url) == before
    assert not list(profile_avatars.directory().glob('*'))


@pytest.mark.parametrize('format,extension', [('PNG','png'),('JPEG','jpg'),('WEBP','webp')])
def test_approved_images_ignore_paths_and_strip_trailing_payload(admin_client, admin, format, extension):
    assert post(admin_client, image=image_bytes(format)+b'<script>bad</script>', filename=f'../../outside.{extension}').status_code == 303
    response = admin_client.get(admin.picture_url)
    assert response.status_code == 200 and b'<script>' not in response.data
    assert profile_avatars.path_for('../../outside.png') is None


def test_animation_is_rejected(admin_client):
    stream = io.BytesIO()
    Image.new('RGB',(64,64),'red').save(stream, format='WEBP', save_all=True, append_images=[Image.new('RGB',(64,64),'blue')], duration=100)
    assert post(admin_client, image=stream.getvalue(), filename='animation.webp').status_code == 422


def test_other_users_and_anonymous_cannot_read_avatar(admin_client, admin, staff_client, anon_client):
    assert post(admin_client, image=image_bytes()).status_code == 303
    url = admin.picture_url
    assert staff_client.get(url).status_code == 404
    assert anon_client.get(url).status_code == 302
    assert anon_client.post('/settings/profile', data={'full_name':'No Access'}).status_code == 302


@pytest.mark.parametrize('field', ['role','email','account_status','user_id','picture_url','verification_status','is_active'])
def test_protected_fields_rejected_without_partial_update(admin_client, admin, staff, field):
    before = (admin.full_name, admin.email, admin.role, admin.account_status, staff.full_name)
    assert post(admin_client, **{field:str(staff.id)}).status_code == 422
    db.session.refresh(admin); db.session.refresh(staff)
    assert (admin.full_name, admin.email, admin.role, admin.account_status, staff.full_name) == before


def test_replacement_and_reset_clean_up_owned_files(admin_client, admin):
    post(admin_client, image=image_bytes()); old = profile_avatars.path_for(admin.picture_url.rsplit('/',1)[-1])
    post(admin_client, image=image_bytes()); new = profile_avatars.path_for(admin.picture_url.rsplit('/',1)[-1])
    assert not old.exists() and new.exists()
    assert post(admin_client, remove_picture='on').status_code == 303
    assert admin.picture_url == '' and not new.exists()
    assert 'Default Profile Avatar' in admin_client.get('/settings').get_data(as_text=True)


def test_google_sync_preserves_user_edits_and_reset(app, admin_client, admin):
    admin.google_sub = 'known-google-sub'; db.session.commit()
    post(admin_client, name='My Chosen Name', image=image_bytes())
    selected = admin.picture_url
    data = {'sub':admin.google_sub, 'email':admin.email, 'email_verified':True, 'name':'Google Name', 'picture':'https://lh3.googleusercontent.com/old.png'}
    user, error = authorize_google_user(data)
    assert not error and user.full_name == 'My Chosen Name' and user.picture_url == selected
    post(admin_client, name='My Chosen Name', remove_picture='on')
    user, error = authorize_google_user(data)
    assert not error and user.picture_url == ''


def test_missing_google_display_data_is_initialized(admin):
    admin.full_name = None; admin.picture_url = None; db.session.commit()
    user, error = authorize_google_user({'sub':'new-sub','email':admin.email,'email_verified':True,'name':'Google Name','picture':'https://lh3.googleusercontent.com/picture.png'})
    assert not error and user.full_name == 'Google Name' and user.picture_url.endswith('picture.png')


@pytest.mark.parametrize('status', AccountStatus.PENDING + AccountStatus.BLOCKED)
def test_profile_update_keeps_existing_account_gate(admin_client, admin, status):
    original = admin.full_name; admin.account_status = status; db.session.commit()
    response = post(admin_client)
    assert response.status_code == (403 if status in AccountStatus.PENDING else 302)
    db.session.refresh(admin); assert admin.full_name == original


def test_missing_csrf_is_rejected(app, admin_client, admin):
    app.config['WTF_CSRF_ENABLED'] = True
    before = admin.full_name
    assert post(admin_client).status_code == 400
    db.session.refresh(admin); assert admin.full_name == before


def test_failed_database_commit_rolls_back_name_and_cleans_upload(admin_client, admin, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    before = admin.full_name
    def fail():
        raise SQLAlchemyError('test database unavailable')
    monkeypatch.setattr(db.session, 'commit', fail)
    assert post(admin_client, image=image_bytes()).status_code == 503
    db.session.refresh(admin); assert admin.full_name == before and not admin.picture_url
    assert not list(profile_avatars.directory().glob('*'))


def test_image_storage_failure_does_not_change_profile(admin_client, admin, monkeypatch):
    before = admin.full_name
    def fail(_):
        raise OSError('test storage unavailable')
    monkeypatch.setattr(profile_avatars, 'save', fail)
    assert post(admin_client, image=image_bytes()).status_code == 503
    db.session.refresh(admin); assert admin.full_name == before
