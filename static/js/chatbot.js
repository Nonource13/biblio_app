// static/js/chatbot.js

// Fonction pour afficher/cacher la fenêtre de chat
function toggleChatWindow() {
    const chatWindow = document.getElementById('chat-window');
    if (chatWindow.style.display === 'none' || chatWindow.style.display === '') {
        chatWindow.style.display = 'flex'; // Utiliser flex car on a défini flex-direction
    } else {
        chatWindow.style.display = 'none';
    }
}

// Fonction pour envoyer un message et obtenir une réponse simulée
async function sendChatMessage() {
    const inputElement = document.getElementById('chat-input');
    const messagesContainer = document.getElementById('chat-messages');
    const userMessage = inputElement.value.trim();

    if (userMessage === '') return;

    appendMessage('Vous', userMessage, messagesContainer, false);
    const messageToSend = inputElement.value;
    inputElement.value = '';

    // *** Afficher l'indicateur AVANT d'envoyer ***
    appendTypingIndicator(messagesContainer);

    try {
        const response = await fetch('/chat', { /* ... options fetch ... */
             method: 'POST',
             headers: { 'Content-Type': 'application/json', },
             body: JSON.stringify({ message: messageToSend })
         });

        // *** Supprimer l'indicateur DÈS qu'on a une réponse (succès ou erreur) ***
        removeTypingIndicator();

        if (!response.ok) {
            console.error("Erreur serveur:", response.status, response.statusText);
            let errorReply = "Désolé, une erreur serveur est survenue.";
            try { const errorData = await response.json(); if (errorData && errorData.reply) errorReply = errorData.reply; } catch(e) {}
            // Afficher le message d'erreur après avoir enlevé l'indicateur
            appendMessage('Bot Erreur', errorReply, messagesContainer, true);
        } else {
            const data = await response.json();
            console.log("Réponse reçue:", data);
            if (data && data.reply) {
                // Afficher la réponse de l'IA après avoir enlevé l'indicateur
                appendMessage('BiblioBot IA', data.reply, messagesContainer, true);
            } else {
                 appendMessage('Bot Erreur', "Réponse invalide du serveur.", messagesContainer, true);
            }
        }
    } catch (error) {
         // *** Supprimer l'indicateur AUSSI en cas d'erreur réseau ***
         removeTypingIndicator();
         console.error("Erreur réseau:", error);
         appendMessage('Bot Erreur', "Impossible de contacter l'assistant (erreur réseau).", messagesContainer, true);
    }
}

// Fonction pour ajouter un message à la zone de chat
function appendMessage(sender, message, container, isBot) {
    const messageDiv = document.createElement('div');
    messageDiv.classList.add('mb-2', 'd-flex', isBot ? 'justify-content-start' : 'justify-content-end');

    const messageBubble = document.createElement('div');
    messageBubble.classList.add('p-2', 'rounded', 'mw-75', 'shadow-sm'); // Ajout ombre légère

    if (isBot) {
        messageBubble.classList.add('bg-light', 'text-dark', 'border');
    } else {
        messageBubble.classList.add('bg-primary', 'text-white');
    }

    // *** Gérer les sauts de ligne (\n) en les remplaçant par <br> ***
    messageBubble.innerHTML = message.replace(/\n/g, '<br>');

    messageDiv.appendChild(messageBubble);
    container.appendChild(messageDiv);
    container.scrollTop = container.scrollHeight;
}

// Fonction contenant la logique de réponse (très simple) du bot
function getBotResponse(userInput) {
    // Logique très basique avec if/else if/else
    if (userInput.includes('horaires')) {
        return "Nos horaires d'ouverture sont de 9h à 18h, du lundi au samedi (Simulation).";
    } else if (userInput.includes('chercher livre') || userInput.includes('trouver livre')) {
        // Extrait simple (ne fonctionne que pour l'exemple)
        const searchTerm = userInput.replace('chercher livre', '').replace('trouver livre', '').trim();
        if (searchTerm) {
            return `Voici des résultats simulés pour "${searchTerm}": [Livre A sur ${searchTerm}], [Livre B sur ${searchTerm}] (Simulation).`;
        } else {
            return "Que souhaitez-vous chercher exactement ?";
        }
    } else if (userInput.includes('bonjour') || userInput.includes('salut')) {
        return "Bonjour ! En quoi puis-je vous aider ?";
    } else if (userInput.includes('merci')) {
         return "De rien ! N'hésitez pas si vous avez d'autres questions.";
    } else {
        return "Je suis désolé, je ne comprends pas cette demande (Simulation). Vous pouvez essayer 'horaires' ou 'chercher livre [sujet]'.";
    }
}

function appendTypingIndicator(container) {
    const typingDiv = document.createElement('div');
    // Ajouter un ID unique pour pouvoir le retrouver facilement
    typingDiv.id = 'typing-indicator-element';
    typingDiv.classList.add('mb-2', 'd-flex', 'justify-content-start');
    typingDiv.innerHTML = `
        <div class="p-2 rounded bg-light text-muted border shadow-sm">
            <div class="spinner-grow spinner-grow-sm text-primary me-1" role="status">
              <span class="visually-hidden">Loading...</span>
            </div>
            <i>BiblioBot IA écrit...</i>
        </div>`;
    container.appendChild(typingDiv);
    container.scrollTop = container.scrollHeight;
    return typingDiv; // On retourne l'élément créé
}

function removeTypingIndicator() {
    // Trouver l'indicateur par son ID et le supprimer
    const indicator = document.getElementById('typing-indicator-element');
    if (indicator) {
        indicator.remove();
    }
}

// Bonus : Permettre d'envoyer avec la touche Entrée
document.getElementById('chat-input').addEventListener('keypress', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChatMessage();
    }
});