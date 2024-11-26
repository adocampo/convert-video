# History and why I did this

---
Usually, when you download from the internet movies and tv shows, you will have plenty of formats and codecs, and if the videos has some age, those codes will be quite unefficient (like AVC codec), occuping a lot of disk space when newer codecs (like AV1) are far more optimized (but not all players can play AV1 nowadays)

I have plenty of space in my home server, but I realized I could save 2/3 of it just by re-enconding all my videos.

At first, I used ffmpeg and when converting from AVC (or H264) to HVEC (or H265), and it saved almost the half of the space.

Then, I've tried AV1, but as I only have an NVidia RTX 3070, I must encode videos in AV1 with my CPU, instead of my GPU, which is a pain in the ass, to be sincere. Compression is awesome, sometimes even x6 times less than H264, and usually x2 time less than H265.

So far, so good, so, I began to do a simple script to automate this with ffpmeg, which all of us have almost preinstalled in our linux boxes.

### The good

But recently I've dowloaded a set of BDRip movies, like 60GB each, and even my script reduced them a lot, still were around 10GB, which I found pretty much of a 100 or 120 minutes movie. So I gave a try to handbrake and used its AV1 preset. The result was impressive: from 60GB in H264 to 2GB in AV1... x30 times less!!!

### The bad

Unfortunately, if you don't have a Nvidia 40X family, you cannot use your GPU to encode with AV1, so enconding a 2h movie will be around 2h with a decent i7 12th generation CPU... too much if you have hundreds of movies, and that doing if via network with your PC, your NAS probably will have a less powerful CPU and it will take a lot longer and probably will hung in the process.

### The ugly

At this point, I find marvelous the preset in HandBrake, how well optimized was and I realized those guys (HandBrake devs) know a lot better than me about encodings ad so, so I did try the H265 preset, and compared the result with my ffmpeg encoding in H265. The results were also astonishing. Handbrake H265 encoding was almost on par (a 15% or so higher) than AV1 when compressing from H264, and it even was able to compress HVEC videos even more!! (ffmpeg wasn't able to reduce a single bit of them). Besides, I can use my GPU and encode them with HVEC_NVENC codec, so compressing 1h of video can take just 4 minutes.

## Requisites

---
You only need to have installed [HandBrakeCLI](https://handbrake.fr/downloads2.php), and be able to run bash scripts.
