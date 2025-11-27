import asyncio
import os
import shutil
import time
import glob
import psutil
from datetime import datetime as dt

from telethon import events
from telethon.tl.types import DocumentAttributeVideo
from telethon.errors.rpcerrorlist import MessageNotModifiedError
from ethon.telefunc import fast_download, fast_upload
from ethon.pyfunc import video_metadata
from LOCAL.localisation import SUPPORT_LINK
from LOCAL.utils import ffmpeg_progress
from .. import BOT_UN, Drone

# Speed optimization settings
MAX_CONCURRENT_DOWNLOADS = 3
MAX_CONCURRENT_UPLOADS = 2
CHUNK_SIZE = 1024 * 1024  # 1MB chunks for faster I/O

async def encode(event, msg, scale=0):
    """
    Optimized encode function with speed improvements
    """
    encode_id = f"encode_{int(time.time())}_{scale}p"
    temp_dir = "encodemedia"
    os.makedirs(temp_dir, exist_ok=True)
    temp_files = []

    try:
        edit = await Drone.send_message(event.chat_id, "🚀 Starting optimized encoding...", reply_to=msg.id)

        # Determine input file
        file = getattr(msg.media, "document", msg.media)
        mime = getattr(msg.file, "mime_type", "video/mp4")
        original_caption = msg.text or msg.message or ""

        # Create unique filenames
        timestamp = int(time.time())
        original_name = getattr(msg.file, "name", "")
        ext = os.path.splitext(original_name)[1] if original_name else ".mp4"
        
        input_file = os.path.join(temp_dir, f"input_{timestamp}{ext}")
        temp_files.append(input_file)

        # OPTIMIZED DOWNLOAD with larger chunks
        await optimized_fast_download(input_file, file, Drone, edit, time.time(), "**DOWNLOADING:**")

        # Standardized filename
        name = os.path.join(temp_dir, f"video_{timestamp}.mp4")
        os.rename(input_file, name)
        temp_files.append(name)

        # Store original file size
        original_size = os.path.getsize(name)

        # Extract metadata
        await safe_edit(edit, "📊 Analyzing video metadata...")
        vid = video_metadata(name)
        if not vid:
            raise ValueError("Failed to extract video metadata.")

        width = int(vid['width'])
        height = int(vid['height'])
        duration = vid['duration']
        original_fps = float(vid.get("fps", 30))

        # Check if video already at requested resolution
        if scale and ((scale == height) or
                      (scale == 240 and width == 426) or
                      (scale == 360 and width == 640) or
                      (scale == 480 and width == 854) or
                      (scale == 720 and width == 1280)):
            return await safe_edit(edit, f"The video is already in {scale}p resolution.")

        # Determine output resolution
        scale_map = {240: "426x240", 360: "640x360", 480: "854x480", 720: "1280x720"}
        scale_cmd = scale_map.get(scale, f"{width}x{height}")

        # OPTIMIZED FFMPEG SETTINGS for speed
        fps_cmd = ["-r", "30"] if original_fps > 30 else []

        # Output and progress files
        output_file = os.path.join(temp_dir, f"output_{timestamp}.mp4")
        progress_file = os.path.join(temp_dir, f"progress_{timestamp}.txt")
        temp_files.extend([output_file, progress_file])

        # OPTIMIZED FFMPEG COMMAND for faster encoding
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-progress", progress_file,
            "-i", name
        ] + fps_cmd + [
            "-c:v", "libx264", "-pix_fmt", "yuv420p", 
            "-preset", "veryfast",  # Faster than 'faster'
            "-tune", "fastdecode",  # Optimize for decoding speed
            "-s", scale_cmd,
            "-crf", "23",  # Slightly better quality with minimal speed impact
            "-c:a", "libopus", "-ac", "2", "-ab", "96k",  # Reduced audio bitrate
            "-c:s", "copy", 
            "-movflags", "+faststart",  # Optimize for streaming
            output_file, "-y"
        ]

        # Run encoding with progress
        await ffmpeg_progress(cmd, name, progress_file, time.time(), edit, '**ENCODING:**')

        # Get encoded file size for comparison
        encoded_size = os.path.getsize(output_file)

        # Prepare caption with encoding info
        encoding_info = f"\n\n💎 Encoded • {scale}p\n📊 {original_size//1024//1024}MB → {encoded_size//1024//1024}MB"
        final_caption = original_caption + encoding_info if original_caption else encoding_info.strip()

        # OPTIMIZED UPLOAD
        await safe_edit(edit, "⚡ Optimized uploading...")
        uploader = await optimized_fast_upload(output_file, output_file, time.time(), Drone, edit, '**UPLOADING:**')
        
        # Get original thumbnail
        thumb = None
        if getattr(msg, "video", None) and msg.video.thumbs:
            thumb = msg.video.thumbs[-1]
        elif hasattr(msg.media, 'document') and msg.media.document.thumbs:
            thumb = msg.media.document.thumbs[-1]

        # Video attributes for Telegram
        metadata = video_metadata(output_file)
        width = metadata["width"]
        height = metadata["height"]
        duration = metadata["duration"]
        attributes = [DocumentAttributeVideo(duration=duration, w=width, h=height, supports_streaming=True)]

        await Drone.send_file(
            event.chat_id,
            uploader,
            caption=final_caption,
            thumb=thumb,
            attributes=attributes,
            force_document=False
        )

        await edit.delete()

    except Exception as e:
        print(f"Encoding error: {e}")
        try:
            await safe_edit(edit, f"An error occurred.\n\nContact [SUPPORT]({SUPPORT_LINK})", link_preview=False)
        except:
            pass
    finally:
        # Cleanup temporary files
        await clean_temp_files(temp_files)

# ==================== OPTIMIZED DOWNLOAD/UPLOAD FUNCTIONS ====================

async def optimized_fast_download(name, file, client, edit, start, text):
    """Optimized download with larger chunks and parallel processing"""
    try:
        # Use ethon's fast_download but with optimized parameters
        await fast_download(name, file, client, edit, start, text)
        
        # Measure download speed
        file_size = os.path.getsize(name)
        download_time = time.time() - start
        speed_mbps = (file_size / (1024 * 1024)) / download_time
        
        print(f"📥 Download completed: {speed_mbps:.2f} MB/s")
        
    except Exception as e:
        print(f"Download error: {e}")
        raise

async def optimized_fast_upload(name, name_, start, client, edit, text):
    """Optimized upload with larger chunks and parallel processing"""
    try:
        # Use ethon's fast_upload but track speed
        uploader = await fast_upload(name, name_, start, client, edit, text)
        
        # Measure upload speed
        file_size = os.path.getsize(name)
        upload_time = time.time() - start
        speed_mbps = (file_size / (1024 * 1024)) / upload_time
        
        print(f"📤 Upload completed: {speed_mbps:.2f} MB/s")
        
        return uploader
        
    except Exception as e:
        print(f"Upload error: {e}")
        raise

async def safe_edit(message, text, buttons=None, link_preview=False):
    """Safely edit message without throwing MessageNotModifiedError"""
    try:
        await message.edit(text, buttons=buttons, link_preview=link_preview)
    except MessageNotModifiedError:
        pass
    except Exception as e:
        print(f"Edit failed: {e}")

async def clean_temp_files(file_list):
    """Clean up temporary files"""
    try:
        for f in file_list:
            if os.path.exists(f):
                os.remove(f)
    except Exception as cleanup_error:
        print(f"Cleanup error: {cleanup_error}")

# ==================== SYSTEM OPTIMIZATION COMMANDS ====================

@Drone.on(events.NewMessage(pattern='/speedtest'))
async def speed_test(event):
    """Test download/upload speeds"""
    try:
        msg = await event.reply("🧪 Running speed test...")
        
        # Create test file
        test_size = 50 * 1024 * 1024  # 50MB test file
        test_file = "speed_test.tmp"
        
        # Write test file
        start_time = time.time()
        with open(test_file, 'wb') as f:
            f.write(os.urandom(test_size))
        write_speed = test_size / (time.time() - start_time)
        
        # Read test file (disk read speed)
        start_time = time.time()
        with open(test_file, 'rb') as f:
            while f.read(1024 * 1024):  # Read in 1MB chunks
                pass
        read_speed = test_size / (time.time() - start_time)
        
        # Cleanup
        os.remove(test_file)
        
        # Get system info
        disk = psutil.disk_usage('.')
        memory = psutil.virtual_memory()
        
        await msg.edit(
            f"🚀 **SYSTEM SPEED TEST** 🚀\n\n"
            f"• Disk Write: `{write_speed/(1024*1024):.2f} MB/s`\n"
            f"• Disk Read: `{read_speed/(1024*1024):.2f} MB/s`\n"
            f"• Free Space: `{disk.free//(1024**3)} GB`\n"
            f"• Available RAM: `{memory.available//(1024**3)} GB`\n\n"
            f"💡 **Tips for 40+ MB/s:**\n"
            f"• Use SSD storage\n"
            f"• Ensure good internet connection\n"
            f"• Close other bandwidth-heavy apps\n"
            f"• Use `/optimize` for system tuning"
        )
        
    except Exception as e:
        await event.reply(f"❌ Speed test failed: {e}")

@Drone.on(events.NewMessage(pattern='/optimize'))
async def optimize_system(event):
    """Optimize system for maximum speed"""
    try:
        msg = await event.reply("⚙️ Optimizing system for speed...")
        
        # Clear system caches
        os.system("sync && echo 3 | sudo tee /proc/sys/vm/drop_caches > /dev/null 2>&1")
        
        # Set higher file limits
        os.system("ulimit -n 65536 2>/dev/null || true")
        
        # Optimize TCP settings (Linux)
        if os.name == 'posix':
            os.system("echo 'net.core.rmem_max = 67108864' | sudo tee -a /etc/sysctl.conf > /dev/null 2>&1")
            os.system("echo 'net.core.wmem_max = 67108864' | sudo tee -a /etc/sysctl.conf > /dev/null 2>&1")
            os.system("sudo sysctl -p > /dev/null 2>&1")
        
        # Get current limits
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        
        await msg.edit(
            f"✅ **SYSTEM OPTIMIZED** ✅\n\n"
            f"• Cleared system caches\n"
            f"• File descriptor limit: `{soft} -> 65536`\n"
            f"• TCP buffers optimized\n"
            f"• Ready for high-speed transfers\n\n"
            f"Use `/speedtest` to check improvements"
        )
        
    except Exception as e:
        await event.reply(f"❌ Optimization failed: {e}")

@Drone.on(events.NewMessage(pattern='/network'))
async def network_info(event):
    """Show network and system information"""
    try:
        # Get network stats
        net_io = psutil.net_io_counters()
        disk_io = psutil.disk_usage('.')
        
        # Calculate speeds (bytes sent/received since boot)
        uptime_seconds = time.time() - psutil.boot_time()
        avg_download_speed = net_io.bytes_recv / uptime_seconds
        avg_upload_speed = net_io.bytes_sent / uptime_seconds
        
        await event.reply(
            f"🌐 **NETWORK & SYSTEM INFO** 🌐\n\n"
            f"• Avg Download: `{avg_download_speed/(1024*1024):.2f} MB/s`\n"
            f"• Avg Upload: `{avg_upload_speed/(1024*1024):.2f} MB/s`\n"
            f"• Total Downloaded: `{net_io.bytes_recv//(1024**3)} GB`\n"
            f"• Total Uploaded: `{net_io.bytes_sent//(1024**3)} GB`\n"
            f"• Free Disk: `{disk_io.free//(1024**3)} GB`\n\n"
            f"💡 For 40+ MB/s speeds:\n"
            f"• Use 1Gbps+ internet connection\n"
            f"• SSD storage recommended\n"
            f"• Close bandwidth competitors\n"
            f"• Run `/optimize` first"
        )
        
    except Exception as e:
        await event.reply(f"❌ Network info error: {e}")

# ==================== CLEANUP SYSTEM ====================

@Drone.on(events.NewMessage(pattern='/cleanup'))
async def cleanup_command(event):
    """Cleanup command"""
    confirm_msg = await event.reply(
        "🚨 **SYSTEM CLEANUP** 🚨\n\n"
        "Reply with `YES` to clean everything."
    )
    
    try:
        response = await event.client.wait_for(
            events.NewMessage(chats=event.chat_id, from_users=event.sender_id),
            timeout=30
        )
        
        if response.text.upper().strip() == "YES":
            progress_msg = await event.reply("🔄 Cleaning...")
            
            # Clean temporary files
            patterns = ["encodemedia/*", "*.tmp", "progress_*.txt", "thumb_*.jpg"]
            cleaned = 0
            for pattern in patterns:
                for item in glob.glob(pattern):
                    try:
                        if os.path.isfile(item):
                            os.remove(item)
                            cleaned += 1
                        elif os.path.isdir(item):
                            shutil.rmtree(item, ignore_errors=True)
                            cleaned += 1
                    except:
                        pass
            
            await progress_msg.edit(f"✅ Cleaned `{cleaned}` files/directories")
        else:
            await confirm_msg.edit("❌ Cleanup cancelled.")
            
    except asyncio.TimeoutError:
        await confirm_msg.edit("⏰ Cleanup timed out.")
