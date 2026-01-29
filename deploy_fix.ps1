# Deploy the snapshot_url fix
$sshCmd = @"
sudo python3 -c "
import re
with open('/opt/streamdisplay/app.py', 'r') as f:
    content = f.read()

old = '''            streams.append({
                'id': cam['id'],
                'name': cam['name'],
                'url': cam['rtsp_url'],
                'type': 'unifi'
            })'''

new = '''            streams.append({
                'id': cam['id'],
                'name': cam['name'],
                'url': cam['rtsp_url'],
                'type': 'unifi',
                'snapshot_url': f'/api/unifi/snapshot/{cam[\"id\"]}',
                'state': cam.get('state', '')
            })'''

if old in content:
    content = content.replace(old, new)
    with open('/opt/streamdisplay/app.py', 'w') as f:
        f.write(content)
    print('PATCHED')
else:
    print('ALREADY_PATCHED')
"
"@

# Run via SSH
& C:\key\plink.exe -batch -i C:\key\private.ppk freezweb@10.1.1.161 $sshCmd
& C:\key\plink.exe -batch -i C:\key\private.ppk freezweb@10.1.1.161 "sudo systemctl restart streamdisplay"
Write-Host "Deploy complete!"
