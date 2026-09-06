import os
cid = os.environ.get("YOUTUBE_CLIENT_ID", "")
csec = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
with open(".yt_creds", "w") as f:
    f.write(cid + "\n" + csec + "\n")
os.chmod(".yt_creds", 0o600)
print("client_id present:", bool(cid), "client_secret present:", bool(csec))
