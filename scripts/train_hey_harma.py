import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

import random
import time
import numpy as np
import scipy.signal
import soundfile as sf
import win32com.client
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import TensorDataset, DataLoader
import onnx
import onnxscript
import onnxruntime as ort

print("=== Starting Dedicated hey_harma.onnx Training Pipeline ===", flush=True)

ASSETS_DIR = "app/src/main/assets/wakeword"
MEL_MODEL_PATH = os.path.join(ASSETS_DIR, "melspectrogram.onnx")
EMB_MODEL_PATH = os.path.join(ASSETS_DIR, "embedding_model.onnx")
OUTPUT_MODEL_PATH = os.path.join(ASSETS_DIR, "hey_harma.onnx")
CACHE_FILE = "scripts/features_cache.npz"
AUDIO_DIR = "scripts/audio_dataset"
os.makedirs(AUDIO_DIR, exist_ok=True)

# 1. Fast SAPI Audio Generation
speaker = win32com.client.Dispatch("SAPI.SpVoice")
available_voices = speaker.GetVoices()
print(f"Available SAPI voices: {available_voices.Count}", flush=True)

positive_phrases = [
    "Hey Harma",
    "Hey, Harma",
    "Hey Harma!",
    "Hey Harma AI",
    "Harma",
    "Hi Harma",
    "OK Harma",
    "Hey Harma please",
]

negative_phrases = [
    "Hey Jarvis",
    "Hey Siri",
    "Hey Google",
    "Hey Alexa",
    "Karma",
    "Homer",
    "Harm",
    "Harmony",
    "Arma",
    "Hammer",
    "Harry",
    "Farmer",
    "Hello",
    "Good morning",
    "What is the time",
    "Open YouTube",
    "Turn on flashlight",
    "Open Paytm",
    "How are you doing",
    "Play some music",
    "Stop the timer",
    "Call mom",
    "Cancel that",
    "Go home",
    "Nice to meet you",
    "Armageddon",
    "Harmonic",
]

rates = [-3, -2, -1, 0, 1, 2, 3]

def generate_tts_files():
    existing_pos = [os.path.join(AUDIO_DIR, f) for f in os.listdir(AUDIO_DIR) if f.startswith("pos_")]
    existing_neg = [os.path.join(AUDIO_DIR, f) for f in os.listdir(AUDIO_DIR) if f.startswith("neg_")]
    if len(existing_pos) >= 100 and len(existing_neg) >= 100:
        print(f"Using {len(existing_pos)} positive and {len(existing_neg)} negative audio clips from existing cache.", flush=True)
        return existing_pos, existing_neg

    print("Generating synthetic speech audio clips via SAPI COM...", flush=True)
    pos_files = []
    neg_files = []

    # Positives
    count = 0
    for v_idx in range(available_voices.Count):
        speaker.Voice = available_voices.Item(v_idx)
        for phrase in positive_phrases:
            for rate in rates:
                speaker.Rate = rate
                path = os.path.join(AUDIO_DIR, f"pos_{count}.wav")
                fs = win32com.client.Dispatch("SAPI.SpFileStream")
                fs.Open(path, 3, False)
                speaker.AudioOutputStream = fs
                speaker.Speak(phrase)
                fs.Close()
                pos_files.append(path)
                count += 1

    # Negatives
    count = 0
    for v_idx in range(available_voices.Count):
        speaker.Voice = available_voices.Item(v_idx)
        for phrase in negative_phrases:
            for rate in [-2, 0, 2]:
                speaker.Rate = rate
                path = os.path.join(AUDIO_DIR, f"neg_{count}.wav")
                fs = win32com.client.Dispatch("SAPI.SpFileStream")
                fs.Open(path, 3, False)
                speaker.AudioOutputStream = fs
                speaker.Speak(phrase)
                fs.Close()
                neg_files.append(path)
                count += 1

    print(f"Generated {len(pos_files)} positive audio clips and {len(neg_files)} negative audio clips.", flush=True)
    return pos_files, neg_files

pos_files, neg_files = generate_tts_files()

# 2. Embedding Extraction Pipeline using ONNX models
mel_sess = ort.InferenceSession(MEL_MODEL_PATH)
emb_sess = ort.InferenceSession(EMB_MODEL_PATH)
mel_input_name = mel_sess.get_inputs()[0].name
emb_input_name = emb_sess.get_inputs()[0].name

CHUNK_SAMPLES = 1280

def audio_to_embedding_frames(audio_16k):
    mel_buffer = np.zeros((1, 76, 32, 1), dtype=np.float32)
    emb_sequence = []

    for start in range(0, len(audio_16k) - CHUNK_SAMPLES, CHUNK_SAMPLES):
        chunk = audio_16k[start:start+CHUNK_SAMPLES].reshape(1, CHUNK_SAMPLES).astype(np.float32)
        mels = mel_sess.run(None, {mel_input_name: chunk})[0]
        new_mels = mels.reshape(-1, 32)
        num_new = new_mels.shape[0]

        mel_buffer[0, :-num_new, :, 0] = mel_buffer[0, num_new:, :, 0]
        mel_buffer[0, -num_new:, :, 0] = new_mels

        emb = emb_sess.run(None, {emb_input_name: mel_buffer})[0].reshape(96)
        emb_sequence.append(emb)

    return np.array(emb_sequence) # shape: [T, 96]

def load_resample(path):
    data, sr = sf.read(path)
    if len(data.shape) > 1:
        data = data[:, 0]
    if sr != 16000:
        num_samples = int(len(data) * 16000 / sr)
        data = scipy.signal.resample(data, num_samples)
    data = data.astype(np.float32)
    max_val = np.max(np.abs(data))
    if max_val < 1.0:
        data = data * 32767.0
    elif max_val > 0:
        data = (data / max_val) * 32767.0
    return data

def augment_audio(data, noise_snr=None, stretch_factor=1.0):
    if stretch_factor != 1.0:
        num_samples = int(len(data) * stretch_factor)
        data = scipy.signal.resample(data, num_samples)
    if noise_snr is not None:
        noise = np.random.randn(len(data)).astype(np.float32)
        signal_pwr = np.mean(data ** 2)
        noise_pwr = np.mean(noise ** 2)
        if noise_pwr > 0:
            scale = np.sqrt(signal_pwr / (10 ** (noise_snr / 10) * noise_pwr))
            data = data + noise * scale
    return data

if os.path.exists(CACHE_FILE):
    print(f"Loading cached embeddings from {CACHE_FILE}...", flush=True)
    cached_data = np.load(CACHE_FILE)
    X_pos = cached_data['X_pos']
    X_neg = cached_data['X_neg']
else:
    print("Extracting speech embeddings with data augmentation...", flush=True)
    X_pos = []
    for p in pos_files:
        raw = load_resample(p)
        for snr in [None, 24, 16]:
            for stretch in [0.93, 1.0, 1.07]:
                aug = augment_audio(raw.copy(), noise_snr=snr, stretch_factor=stretch)
                lead_silence = np.zeros(random.randint(640, 4800), dtype=np.float32)
                trail_silence = np.zeros(random.randint(1280, 6400), dtype=np.float32)
                padded = np.concatenate([lead_silence, aug, trail_silence])
                embs = audio_to_embedding_frames(padded)
                if len(embs) >= 16:
                    for w_end in range(16, len(embs), 2):
                        window = embs[w_end-16:w_end]
                        X_pos.append(window)

    X_neg = []
    for p in neg_files:
        raw = load_resample(p)
        for snr in [None, 20]:
            aug = augment_audio(raw.copy(), noise_snr=snr, stretch_factor=1.0)
            lead_silence = np.zeros(random.randint(640, 3200), dtype=np.float32)
            padded = np.concatenate([lead_silence, aug])
            embs = audio_to_embedding_frames(padded)
            if len(embs) >= 16:
                for w_end in range(16, len(embs), 3):
                    window = embs[w_end-16:w_end]
                    X_neg.append(window)

    # Add synthetic pure noise / ambient negatives
    for _ in range(400):
        noise_audio = (np.random.randn(random.randint(16000, 32000)) * 600.0).astype(np.float32)
        embs = audio_to_embedding_frames(noise_audio)
        if len(embs) >= 16:
            X_neg.append(embs[:16])

    X_pos = np.array(X_pos, dtype=np.float32)
    X_neg = np.array(X_neg, dtype=np.float32)
    print(f"Saving extracted embeddings to {CACHE_FILE}...", flush=True)
    np.savez_compressed(CACHE_FILE, X_pos=X_pos, X_neg=X_neg)

print(f"Total positive windows: {len(X_pos)}, Total negative windows: {len(X_neg)}", flush=True)

# Balance dataset
min_count = min(len(X_pos), len(X_neg))
np.random.seed(42)
np.random.shuffle(X_pos)
np.random.shuffle(X_neg)

X_pos = X_pos[:min_count]
X_neg = X_neg[:min_count]

X = np.concatenate([X_pos, X_neg], axis=0) # [N, 16, 96]
y = np.concatenate([np.ones((len(X_pos), 1), dtype=np.float32), np.zeros((len(X_neg), 1), dtype=np.float32)], axis=0)

perm = np.random.permutation(len(X))
X = X[perm]
y = y[perm]

# Train / val split (85% / 15%)
split = int(0.85 * len(X))
X_train, y_train = torch.tensor(X[:split]), torch.tensor(y[:split])
X_val, y_val = torch.tensor(X[split:]), torch.tensor(y[split:])

train_dataset = TensorDataset(X_train, y_train)
val_dataset = TensorDataset(X_val, y_val)

train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
val_loader = DataLoader(val_dataset, batch_size=64, shuffle=False)

# 3. Model Definition (matching openWakeWord MLP architecture)
class HeyHarmaClassifier(nn.Module):
    def __init__(self):
        super().__init__()
        self.flatten = nn.Flatten()
        self.fc1 = nn.Linear(16 * 96, 128)
        self.ln1 = nn.LayerNorm(128)
        self.relu1 = nn.ReLU()
        self.drop1 = nn.Dropout(0.15)
        self.fc2 = nn.Linear(128, 128)
        self.ln2 = nn.LayerNorm(128)
        self.relu2 = nn.ReLU()
        self.drop2 = nn.Dropout(0.15)
        self.fc3 = nn.Linear(128, 1)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        h = self.flatten(x)
        h = self.relu1(self.ln1(self.fc1(h)))
        h = self.drop1(h)
        h = self.relu2(self.ln2(self.fc2(h)))
        h = self.drop2(h)
        out = self.sigmoid(self.fc3(h))
        return out

model = HeyHarmaClassifier()
criterion = nn.BCELoss()
optimizer = optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=3)

print("Training Hey Harma classifier...", flush=True)

for epoch in range(1, 31):
    model.train()
    total_loss = 0.0
    correct = 0
    total = 0

    for bx, by in train_loader:
        optimizer.zero_grad()
        preds = model(bx)
        loss = criterion(preds, by)
        loss.backward()
        optimizer.step()

        total_loss += loss.item() * len(bx)
        correct += ((preds >= 0.5) == (by >= 0.5)).sum().item()
        total += len(bx)

    train_loss = total_loss / total
    train_acc = correct / total

    # Validation
    model.eval()
    val_loss = 0.0
    val_correct = 0
    val_total = 0

    with torch.no_grad():
        for bx, by in val_loader:
            preds = model(bx)
            loss = criterion(preds, by)
            val_loss += loss.item() * len(bx)
            val_correct += ((preds >= 0.5) == (by >= 0.5)).sum().item()
            val_total += len(bx)

    val_loss /= val_total
    val_acc = val_correct / val_total
    scheduler.step(val_loss)

    if epoch % 5 == 0 or epoch == 30:
        print(f"Epoch {epoch:2d}/30 | Train Loss: {train_loss:.4f}, Acc: {train_acc*100:.1f}% | Val Loss: {val_loss:.4f}, Acc: {val_acc*100:.1f}%", flush=True)

# 4. Export to self-contained ONNX (dynamo=False for embedded weights and opset 13)
print(f"Exporting self-contained model to {OUTPUT_MODEL_PATH}...", flush=True)
model.eval()
dummy_input = torch.randn(1, 16, 96, dtype=torch.float32)

data_file = OUTPUT_MODEL_PATH + ".data"
if os.path.exists(data_file):
    os.remove(data_file)

torch.onnx.export(
    model,
    dummy_input,
    OUTPUT_MODEL_PATH,
    export_params=True,
    opset_version=13,
    do_constant_folding=True,
    dynamo=False,
    input_names=['input'],
    output_names=['output'],
    dynamic_axes={
        'input': {0: 'batch_size'},
        'output': {0: 'batch_size'}
    }
)

# 5. Verification with ONNX Runtime
print("Verifying exported ONNX model...", flush=True)
verify_sess = ort.InferenceSession(OUTPUT_MODEL_PATH)
test_inp_name = verify_sess.get_inputs()[0].name
test_out_name = verify_sess.get_outputs()[0].name

val_preds = []
for i in range(min(100, len(X_val))):
    sample = X_val[i:i+1].numpy()
    score = verify_sess.run([test_out_name], {test_inp_name: sample})[0][0][0]
    val_preds.append((score, y_val[i].item()))

pos_scores = [s for s, label in val_preds if label == 1.0]
neg_scores = [s for s, label in val_preds if label == 0.0]

print(f"=== Verification Summary ===", flush=True)
print(f"- Positive samples average score: {np.mean(pos_scores):.3f} (min: {np.min(pos_scores):.3f})", flush=True)
print(f"- Negative samples average score: {np.mean(neg_scores):.3f} (max: {np.max(neg_scores):.3f})", flush=True)
print(f"Dedicated hey_harma.onnx successfully generated and verified! Size: {os.path.getsize(OUTPUT_MODEL_PATH)} bytes", flush=True)
