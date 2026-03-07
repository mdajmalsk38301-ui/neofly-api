const express = require('express');
const { exec } = require('child_process');

const app = express();
const PORT = 3000;

// Health Check Endpoint
app.get('/health', (req, res) => {
    res.status(200).json({ message: 'API is running!' });
});

// Video Download Endpoint
app.get('/download', (req, res) => {
    const videoUrl = req.query.url;
    if (!videoUrl) {
        return res.status(400).json({ error: 'URL parameter is required.' });
    }

    // Use yt-dlp to download the video
    exec(`yt-dlp ${videoUrl}`, (error, stdout, stderr) => {
        if (error) {
            return res.status(500).json({ error: 'Failed to download video.', details: stderr });
        }
        res.status(200).send(stdout);
    });
});

// Start the server
app.listen(PORT, () => {
    console.log(`Server is running on port ${PORT}`);
});

