# Kalenda — Your AI Calendar Assistant

Kalenda is a smart WhatsApp-based assistant powered by a **Large Language Model (LLM)** to help busy individuals and families manage their schedules effortlessly. It uses **natural language understanding** on top of **Google Calendar API Integration** to make event tracking as easy as sending a message.

---

## Background

Between school events, birthday invites, doctor appointments, and daily chaos, staying organized is harder than it looks — especially when you're the default scheduler at home. Opening Google Calendar and typing in each event one-by-one can be tedious.

Kalenda aims to:

- Make scheduling feel conversational, not technical
- Let you **create events by sending a text, screenshot, or voice note**
- Simplify calendar management for busy parents, professionals, and caretakers
- Reduce mental load from remembering dates, times, and deadlines

---

## 🔧 Key Features

- **Natural Language Input**  
  Add events simply by texting things like:  
  _"Mary’s ballet recital Saturday 3PM at Kemang Village"_

- **Image Parsing**  
  Forward a photo of a flyer or invitation — Kalenda will extract event info automatically

- **Voice Support**  
  Don’t feel like typing? Send a voice note — Kalenda transcribes and schedules it for you

- **Fetch Calendar Events**  
  Kalenda is able to fetch and summarize your calendar events
  
- **Analyze Avalability Slots**
  Kalenda's smart analyzer can find you availability based on your current calendar slots

- **Google Calendar Integration (Optional)**  
  Securely connect your Google Calendar so Kalenda can add and fetch events directly to your own calendar

- **Shared Test Calendar Mode**  
  Use Kalenda’s shared calendar to try things out without needing to connect your own

---

## 🔁 How It Works

### 📲 User Input → 🧠 Human Language Processing with AI → 📆 Calendar Action

---

## Who It's For

Kalenda is perfect for:

- Parents juggling school, daycare, and appointments  
- Professionals who prefer messaging over app interfaces  
- Anyone who wants to get organized without opening a calendar app

---

## Privacy First
We never sell or share your data. Calendar access is optional and revocable. See [Privacy Policy](./docs/privacy.md) for details.

---

## 🛠️ Architecture Overview
User (WhatsApp)
    │
    ▼
Twilio WhatsApp Webhook
    │
    ▼
Flask API (Kalenda)
    │
 ┌───────────────────────────────┐
 │ AI Processing (OpenAI GPT)    │
 │ OCR/Transcription (Whisper)   │
 └───────────────────────────────┘
    │
    ▼
Google Calendar API (Public/Shared Test Calendar or Personal Calendar)
    │
    ▼
MongoDB (Token Storage, User Data)

---

Stay organized. Stay human. Just message Kalenda.

