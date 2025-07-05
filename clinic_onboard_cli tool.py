# clinic_onboard_cli.py
import asyncio
import click
from initialize_clinic import ClinicInitializer
import os
from dotenv import load_dotenv

load_dotenv()

@click.command()
@click.option('--name', prompt='Clinic name', help='Name of the clinic')
@click.option('--phone', prompt='Phone number', help='Main reception phone number')
@click.option('--api-key', prompt='Cliniko API key', hide_input=True, help='Cliniko API key')
@click.option('--shard', prompt='Cliniko shard', type=click.Choice(['au1', 'au2', 'au3', 'au4', 'uk1', 'us1']), help='Cliniko shard')
@click.option('--email', prompt='Contact email', help='Admin contact email')
def onboard_clinic(name, phone, api_key, shard, email):
    """Onboard a new clinic interactively"""
    
    clinic_data = {
        'clinic_name': name,
        'phone_number': phone,
        'cliniko_api_key': api_key,
        'cliniko_shard': shard,
        'contact_email': email
    }
    
    click.echo(f"\n🏥 Onboarding {name}...")
    
    async def run_onboarding():
        db_url = os.getenv('SUPABASE_DB_URL') or os.getenv('DATABASE_URL')
        
        async with ClinicInitializer(db_url) as initializer:
            results = await initializer.initialize_clinic(clinic_data)
            
        if results['errors']:
            click.echo(click.style(f"\n❌ Failed: {', '.join(results['errors'])}", fg='red'))
        else:
            click.echo(click.style("\n✅ Success!", fg='green'))
            click.echo(f"Clinic ID: {results['clinic_id']}")
            click.echo(f"Practitioners: {results['practitioners']}")
            click.echo(f"Services: {results['appointment_types']}")
            click.echo(f"Time: {results.get('elapsed_seconds', 0):.2f} seconds")
    
    asyncio.run(run_onboarding())

if __name__ == '__main__':
    onboard_clinic()