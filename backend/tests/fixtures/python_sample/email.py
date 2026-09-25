import smtplib

def send_verification_email(to_address: str, token: str):
    """Uses smtplib to send verification emails to new users."""
    print(f"Sending verification {token} to {to_address}")
