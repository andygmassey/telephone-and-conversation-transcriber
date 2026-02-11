# Setting Up Your Raspberry Pi From Scratch

Never used a Raspberry Pi before? No worries — this guide will walk you through every step.

## What you'll need

- A Raspberry Pi 5 (the 8GB version is best, but 4GB works too)
- A microSD card (32GB or bigger)
- A USB keyboard and mouse (just for the initial setup)
- A screen — either the 10" touchscreen you'll be using, or any monitor with HDMI
- A WiFi connection
- Another computer (Mac, Windows, or Linux) to prepare the SD card

## Step 1: Prepare the SD card

1. On your other computer, download **Raspberry Pi Imager** from [raspberrypi.com/software](https://www.raspberrypi.com/software/)
2. Plug the microSD card into your computer
3. Open Raspberry Pi Imager
4. Click **Choose Device** and pick your Raspberry Pi model
5. Click **Choose OS** and pick **Raspberry Pi OS (64-bit)** — it's usually the first option
6. Click **Choose Storage** and pick your SD card
7. Click **Next** — it will ask if you want to customise settings. Click **Edit Settings** and:
   - Set a username and password you'll remember
   - Enter your WiFi name and password
   - Set the hostname to **gramps** (this lets you find it at gramps.local later)
   - Under the **Services** tab, tick **Enable SSH** (so you can control it from another computer)
8. Click **Save**, then **Yes** to start writing

This takes a few minutes. When it's done, pop the SD card out.

## Step 2: Start up the Pi

1. Put the SD card into the Raspberry Pi
2. Plug in the screen, keyboard, and mouse
3. Plug in the power — it'll boot up automatically
4. Wait for it to finish setting up (it may reboot once — that's normal)
5. After a minute or two you should see the desktop

## Step 3: Install the transcriber

Open a terminal (there's an icon at the top of the screen that looks like a black rectangle) and paste this:

```
curl -sSL https://raw.githubusercontent.com/andygmassey/telephone-and-conversation-transcriber/main/install.sh | bash
```

Press Enter and wait. It'll show you its progress as it goes — the whole thing takes about 5-10 minutes.

## Step 4: Finish setup in your browser

When the installer finishes, it'll show you a web address. Open it on your phone or another computer:

**http://gramps.local:8080**

The setup page will walk you through picking your microphones and setting up speech recognition.

## Step 5: Plug in your microphones

- Plug the room microphone (the conference mic) into any USB port
- If you have the phone recorder, plug that in too

Go back to the setup page and it should find them automatically.

That's it! Once you click "Start the transcriber", it'll start showing captions on screen.

---

## Making an SD card image to share

If you've got everything working and want to make a copy of your SD card (so you can set up another Pi without going through all the steps again):

1. Shut down the Pi cleanly: `sudo shutdown -h now`
2. Take the SD card out and put it in your computer
3. On Mac: `sudo dd if=/dev/diskN of=gramps-transcriber.img bs=4m` (replace diskN with your SD card)
4. On Linux: `sudo dd if=/dev/mmcblk0 of=gramps-transcriber.img bs=4M`
5. Compress it: `xz -9 gramps-transcriber.img` (makes it much smaller for sharing)

The resulting `.img.xz` file can be flashed onto another SD card using Raspberry Pi Imager (choose "Use custom" when picking the OS).

**Important:** Before making the image, remove any personal info:
```
rm ~/gramps-transcriber/credentials.py
rm ~/gramps-transcriber/config.json
```

For reproducible, automated builds, look into [pi-gen](https://github.com/RPi-Distro/pi-gen) or [rpi-image-gen](https://github.com/nicholasjackson/rpi-image-gen).
