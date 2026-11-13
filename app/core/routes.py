"""Current-user settings and narrowly scoped profile updates."""
from flask import abort, flash, make_response, redirect, render_template, request, Response, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from app.core import bp, profile_avatars
from app.core.decorators import role_required
from app.extensions import db, limiter
from app.models import AccountStatus, Role


def _settings(status=200, **context):
    response = make_response(render_template(
        'core/personal_settings.html', account_labels=AccountStatus.LABELS,
        profile_errors=context.get('profile_errors', {}),
        profile_name=context.get('profile_name', current_user.full_name or ''),
    ), status)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@bp.get('/settings')
@login_required
@role_required(Role.ADMIN, Role.STAFF)
def personal_settings():
    return _settings()


@bp.post('/settings/profile')
@login_required
@role_required(Role.ADMIN, Role.STAFF)
@limiter.limit('20 per minute')
def update_profile():
    errors = {}
    raw_name = request.form.get('full_name', '')
    name = ' '.join(raw_name.split())
    if not 2 <= len(name) <= 150 or any(ord(char) < 32 and not char.isspace() for char in raw_name):
        errors['full_name'] = 'Enter your full name (2 to 150 characters).'
    allowed = {'csrf_token', 'full_name', 'remove_picture'}
    if set(request.form) - allowed or set(request.files) - {'profile_picture'}:
        errors['form'] = 'Only Full Name and Profile Picture can be updated.'
    if len(request.form.getlist('full_name')) != 1 or len(request.files.getlist('profile_picture')) > 1:
        errors['form'] = 'Submit one profile update at a time.'
    remove = request.form.get('remove_picture', '')
    upload = request.files.get('profile_picture')
    has_upload = upload is not None and bool(upload.filename)
    if remove not in ('', 'on') or (remove and has_upload):
        errors['profile_picture'] = 'Choose a new picture or remove the current one, not both.'
    if errors:
        return _settings(422, profile_errors=errors, profile_name=raw_name)
    new_file = None
    try:
        if has_upload:
            new_file, error = profile_avatars.save(upload)
            if error:
                return _settings(422, profile_errors={'profile_picture': error}, profile_name=raw_name)
        old_file = profile_avatars.stored_name(current_user.picture_url)
        current_user.full_name = name
        if new_file:
            current_user.picture_url = url_for('core.profile_avatar', filename=new_file)
        elif remove:
            # Empty string deliberately retains the initials fallback across future Google logins.
            current_user.picture_url = ''
        db.session.commit()
    except (OSError, SQLAlchemyError):
        db.session.rollback()
        if new_file:
            profile_avatars.delete(new_file)
        return _settings(503, profile_errors={'form': 'Your profile could not be saved. Please try again.'}, profile_name=raw_name)
    if old_file and (new_file or remove):
        profile_avatars.delete(old_file)
    flash('Your profile has been updated.', 'success')
    return redirect(url_for('core.personal_settings'), code=303)


@bp.get('/settings/avatar/<filename>')
@login_required
@role_required(Role.ADMIN, Role.STAFF)
def profile_avatar(filename):
    if profile_avatars.stored_name(current_user.picture_url) != filename:
        abort(404)
    path = profile_avatars.path_for(filename)
    if path is None:
        abort(404)
    try:
        data = path.read_bytes()
    except OSError:
        abort(404)
    response = Response(data, mimetype='image/png')
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
