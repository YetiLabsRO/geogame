from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def send_invite_email(invite, invitee_name=''):
    """Send the invite email. Returns the number of messages delivered."""
    if not invite.email:
        return 0

    accept_url = f'{settings.BASE_URL}/invite/{invite.token}'
    inviter = invite.created_by
    inviter_name = ''
    if inviter is not None:
        inviter_name = inviter.get_full_name() or inviter.get_username()

    team_group = invite.team.group.name if invite.team.group else ''

    context = {
        'team_name': invite.team.name,
        'team_group': team_group,
        'invitee_name': invitee_name,
        'inviter_name': inviter_name,
        'accept_url': accept_url,
        'expires_at': invite.expires_at,
    }
    subject = f'Ești invitat în echipa {invite.team.name}'
    text_body = render_to_string('organize/email/invite.txt', context)
    html_body = render_to_string('organize/email/invite.html', context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[invite.email],
    )
    message.attach_alternative(html_body, 'text/html')
    return message.send()
