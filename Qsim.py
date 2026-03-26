import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit_aer import Aer
import random
import hashlib
import base64
import qutip
import time
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from scipy.special import hermite
from math import factorial
import os
class Qsim:
    def __init__(self, num_bits=32, use_quantum_memory=False, default_eve_active=False):
        self.simulator = Aer.get_backend('qasm_simulator')
        self.num_bits = num_bits
        self.use_quantum_memory = use_quantum_memory
        self.default_eve_active = default_eve_active

    def _xor_bytes(self, data_bytes, key_hash):
        xor_result = bytearray(len(data_bytes))
        for i in range(len(data_bytes)):
            xor_result[i] = data_bytes[i] ^ key_hash[i % len(key_hash)]
        return bytes(xor_result)

    def encrypt_message(self, plaintext_message, quantum_key_str):
        message_bytes = plaintext_message.encode('utf-8')
        key_material = quantum_key_str.encode('utf-8')
        key_hash = hashlib.sha256(key_material).digest()

        encrypted_bytes = self._xor_bytes(message_bytes, key_hash)
        return base64.b64encode(encrypted_bytes).decode('ascii')

    def decrypt_message(self, base64_encrypted_message, quantum_key_str):
        try:
            encrypted_bytes = base64.b64decode(base64_encrypted_message.encode('ascii'))
        except (base64.binascii.Error, UnicodeEncodeError):
            return "[Неверные данные Base64]"

        key_material = quantum_key_str.encode('utf-8')
        key_hash = hashlib.sha256(key_material).digest()

        decrypted_bytes = self._xor_bytes(encrypted_bytes, key_hash)
        return decrypted_bytes.decode('utf-8', errors='replace')

    def simulate_qkd_bb84(self, num_bits, eve_active=False):
        alice_bits = np.random.randint(2, size=num_bits)
        alice_bases = np.random.randint(2, size=num_bits)

        bob_measurements = []

        for i in range(num_bits):
            qc = QuantumCircuit(1, 1)

            if alice_bits[i] == 1: qc.x(0)
            if alice_bases[i] == 1: qc.h(0)

            if eve_active:
                eve_basis = random.choice([0, 1])
                if eve_basis == 1: qc.h(0)
                qc.measure(0, 0)

                res_eve = self.simulator.run(transpile(qc, self.simulator), shots=1).result().get_counts()
                e_bit = int(max(res_eve, key=res_eve.get))

                qc = QuantumCircuit(1, 1)
                if e_bit == 1: qc.x(0)
                if eve_basis == 1: qc.h(0)

            bob_basis = random.choice([0, 1])
            if bob_basis == 1: qc.h(0)
            qc.measure(0, 0)

            job = self.simulator.run(transpile(qc, self.simulator), shots=1)
            res_bob = job.result().get_counts()
            b_bit = int(max(res_bob, key=res_bob.get))

            bob_measurements.append({'bit': b_bit, 'basis': bob_basis})

        agreed_key_alice = []
        agreed_key_bob = []

        for i in range(num_bits):
            if alice_bases[i] == bob_measurements[i]['basis']:
                agreed_key_alice.append(alice_bits[i])
                agreed_key_bob.append(bob_measurements[i]['bit'])

        key_alice = "".join(map(str, agreed_key_alice))
        key_bob = "".join(map(str, agreed_key_bob))

        errors = sum(a != b for a, b in zip(agreed_key_alice, agreed_key_bob))
        qber = (errors / len(agreed_key_alice)) * 100 if len(agreed_key_alice) > 0 else 0

        return qber, key_alice, key_bob

    def classical_message_exchange(self, shared_key):
        print("\n--- Классический обмен сообщениями через безопасный канал ---")

        alice_messages = [
            "Привет, Боб! Это Алиса.",
            "Как насчет обеда завтра?",
            "Кодовое слово: 'Квант'"
        ]
        for msg in alice_messages:
            print(f"Алиса отправляет: '{msg}'")
            encrypted_msg = self.encrypt_message(msg, shared_key)
            print(f"    Алиса отправляет (зашифровано Base64): '{encrypted_msg}'")

            eve_wrong_key = "wrong_guessed_key_by_eve_1234567890"
            eve_decrypted_attempt = self.decrypt_message(encrypted_msg, eve_wrong_key)
            print(f"    [!] ЕВА: Перехватила пакет. Пытается расшифровать с 'неправильным' ключом '{eve_wrong_key[:20]}...'...")
            print(f"    Ева получает: '{eve_decrypted_attempt}' (Мусор)")

            bob_decrypted_msg = self.decrypt_message(encrypted_msg, shared_key)
            print(f"    Боб получает и расшифровывает: '{bob_decrypted_msg}'")
            print("------------------------------")

        bob_messages = [
            "Привет, Алиса! Отлично, давай пообедаем.",
            "Подтверждаю: 'Квант'.",
            "Могу предложить пиццу или суши?"
        ]
        for msg in bob_messages:
            print(f"Боб отправляет: '{msg}'")
            encrypted_msg = self.encrypt_message(msg, shared_key)
            print(f"    Боб отправляет (зашифровано Base64): '{encrypted_msg}'")

            eve_wrong_key = "wrong_guessed_key_by_eve_1234567890"
            eve_decrypted_attempt = self.decrypt_message(encrypted_msg, eve_wrong_key)
            print(f"    [!] ЕВА: Перехватила пакет. Пытается расшифровать с 'неправильным' ключом '{eve_wrong_key[:20]}...'...")
            print(f"    Ева получает: '{eve_decrypted_attempt}' (Мусор)")

            alice_decrypted_msg = self.decrypt_message(encrypted_msg, shared_key)
            print(f"    Алиса получает и расшифровывает: '{alice_decrypted_msg}'")
            print("------------------------------")

    def find_secure_channel(self, num_bits, eve_active=True, max_attempts=100, qber_threshold=10):
        print(f"\n--- Попытка установить безопасный канал (количество бит: {num_bits}, Ева: {'Активна' if eve_active else 'Выключена'}, Порог QBER: <{qber_threshold}%) ---")
        attempt = 0
        qber = 100
        shared_key = ""

        while qber >= qber_threshold and attempt < max_attempts:
            attempt += 1
            print(f"\nПопытка {attempt}: Перезапуск на новой 'частоте'...")
            qber, key_alice, key_bob = self.simulate_qkd_bb84(num_bits, eve_active)

            print(f"    Сформированный ключ Алисы: {key_alice[:20]}...")
            print(f"    Сформированный ключ Боба:  {key_bob[:20]}...")
            print(f"    Уровень квантовых битовых ошибок (QBER): {qber:.1f}%")

            if qber < qber_threshold:
                print(f"[OK] Безопасный канал установлен на попытке {attempt}! QBER = {qber:.1f}%. Ключи используются для связи.\n")
                shared_key = key_alice
                self.classical_message_exchange(shared_key)
                break
            else:
                print(f"[!] Обнаружены ошибки ({qber:.1f}%) или QBER выше допустимого порога (<{qber_threshold}%). Попытка установить канал снова.\n")

        if qber >= qber_threshold:
            print(f"[ВНИМАНИЕ] Не удалось установить безопасный канал после {max_attempts} попыток. QBER = {qber:.1f}%")
            return ""
        return shared_key

    def _get_psi_n_x(self, n, x):
        norm = 1.0 / np.sqrt(2**n * factorial(n)) * (np.pi**(-0.25))
        return norm * np.exp(-x**2 / 2.0) * hermite(n)(x)

    def display_2d_harmonic_oscillator_animation(self, save_video=False, gif_filename='2D_harmonic_oscillator.gif'):
        print("\n--- Запуск 2D анимации гармонического осциллятора ---")

        x_lim = (-5, 5)
        y_lim = (-5, 5)
        grid_points = 100
        t_frames = 100
        speed = 1.0
        hbar_val = 1.0
        omega = 1.0

        x_vec = np.linspace(x_lim[0], x_lim[1], grid_points)
        y_vec = np.linspace(y_lim[0], y_lim[1], grid_points)
        X, Y = np.meshgrid(x_vec, y_vec)

        n_max_x = 3
        n_max_y = 3

        psi_basis_x = [self._get_psi_n_x(n, x_vec) for n in range(n_max_x)]
        psi_basis_y = [self._get_psi_n_x(n, y_vec) for n in range(n_max_y)]

        coeffs = {}
        coeffs[(0,0)] = 1.0 + 0.5j
        coeffs[(1,0)] = 0.8 - 0.2j
        coeffs[(0,1)] = 0.7 + 0.3j
        coeffs[(1,1)] = 0.6 - 0.1j
        coeffs[(2,0)] = 0.4
        coeffs[(0,2)] = 0.4

        total_amplitude_sq = sum(np.abs(c)**2 for c in coeffs.values())
        norm_factor = np.sqrt(total_amplitude_sq)
        for k in coeffs:
            coeffs[k] /= norm_factor

        psi_2d_basis = {}
        energies_2d = {}

        for nx in range(n_max_x):
            for ny in range(n_max_y):
                if (nx, ny) in coeffs:
                    psi_2d_basis[(nx, ny)] = np.outer(psi_basis_y[ny], psi_basis_x[nx])
                    energies_2d[(nx, ny)] = (nx + ny + 1) * hbar_val * omega

        fig, ax = plt.subplots(figsize=(8, 7))
        ax.set_aspect('equal', adjustable='box')
        ax.set_xlim(x_lim)
        ax.set_ylim(y_lim)
        ax.set_title('Вероятностная плотность 2D гармонического осциллятора', fontsize=14)
        ax.set_xlabel('Положение X', fontsize=12)
        ax.set_ylabel('Положение Y', fontsize=12)

        potential_2d = 0.5 * (X**2 + Y**2)
        ax.contour(X, Y, potential_2d, levels=np.linspace(0, 10, 10), colors='gray', linestyles='--', alpha=0.5)

        im = ax.imshow(np.zeros((grid_points, grid_points)), origin='lower', extent=[x_lim[0], x_lim[1], y_lim[0], y_lim[1]], cmap='viridis', vmin=0, vmax=0.1)
        cbar = fig.colorbar(im, ax=ax, label='|Ψ(x, y, t)|²')

        def init():
            im.set_array(np.zeros((grid_points, grid_points)))
            return [im]

        def update(frame):
            t = (frame / t_frames) * 2 * np.pi * speed

            psi_t_2d = np.zeros_like(X, dtype=complex)
            for (nx, ny), coeff in coeffs.items():
                psi_t_2d += coeff * np.exp(-1j * energies_2d[(nx, ny)] * t / hbar_val) * psi_2d_basis[(nx, ny)]

            prob_density_2d = np.abs(psi_t_2d)**2
            im.set_array(prob_density_2d)
            return [im]

        ani_2d = FuncAnimation(fig, update, frames=t_frames, init_func=init, blit=True)

        plt.show()

        if save_video:
            print(f"Сохранение анимации в файл: {gif_filename}")
            try:
                ani_2d.save(gif_filename, writer='pillow', fps=20, dpi=100)
                if os.path.exists(gif_filename):
                    print(f'Анимация успешно сохранена в файл: {gif_filename}')
                else:
                    print('Ошибка: Файл анимации не был создан.')
            except Exception as e:
                print(f"Произошла ошибка при сохранении анимации: {e}")
        else:
            print("Анимация не была сохранена.")
        print("--- 2D анимация гармонического осциллятора завершена ---")

    def run_demonstration(self):
        print("\n" + "="*50 + "\n")
        print("--- ДЕМОНСТРАЦИЯ: Квантовый интернет + Квантовая память ---")

        print("\n" + "*"*20 + " УСТАНОВКА БЕЗОПАСНОГО КАНАЛА " + "*"*20)
        shared_key_AB = self.find_secure_channel(self.num_bits, eve_active=self.default_eve_active, qber_threshold=10)

        if not shared_key_AB:
            print("\n[!] Не удалось установить безопасный QKD-ключ. Демонстрация памяти отменена.")
        else:
            if self.use_quantum_memory:
                quantum_server = QuantumMemoryServer(num_qudit_levels=10, memory_capacity_qudits=300)
                print(f"\nQKD-ключ для A-B: {shared_key_AB[:20]}...")

                print("\n" + "*"*20 + " БОБ ХРАНИТ ПАРОЛЬ НА СЕРВЕРЕ " + "*"*20)
                bob_secret_password = "MySuperSecureWalletPassword123"
                print(f"Боб: Мой пароль для хранения: '{bob_secret_password}'")

                encrypted_password_base64 = self.encrypt_message(bob_secret_password, shared_key_AB)
                print(f"Боб: Зашифрованный (Base64) пароль: '{encrypted_password_base64}'")

                quantum_server.store_client_data("Bob", encrypted_password_base64)

                print("\n" + "*"*20 + " БОБ ЗАПРАШИВАЕТ ПАРОЛЬ С СЕРВЕРА " + "*"*20)
                retrieved_encrypted_base64 = quantum_server.retrieve_client_data("Bob")

                if retrieved_encrypted_base64:
                    decrypted_password = self.decrypt_message(retrieved_encrypted_base64, shared_key_AB)
                    print(f"Боб: Расшифрованный пароль: '{decrypted_password}'")
                    assert decrypted_password == bob_secret_password
                    print("[OK] Пароль успешно сохранен и извлечен Бобом.")
                else:
                    print("[ОШИБКА] Боб не смог извлечь пароль.")

                print("\n" + "*"*20 + " ЕВА ПЫТАЕТСЯ ВМЕШАТЬСЯ " + "*"*20)
                eve_wrong_key = "wrong_guessed_key_by_eve_1234567890"
                print(f"Ева: Пытается запросить данные Боба...")
                eve_retrieved_encrypted_base64 = quantum_server.retrieve_client_data("Bob")

                if eve_retrieved_encrypted_base64:
                    print(f"Ева: Получила зашифрованные (Base64) данные: '{eve_retrieved_encrypted_base64}'")
                    eve_decrypted_attempt = self.decrypt_message(eve_retrieved_encrypted_base64, eve_wrong_key)
                    print(f"Ева: Пытается расшифровать своим ключом: '{eve_wrong_key[:20]}...\nЕва получает: '{eve_decrypted_attempt}' (Мусор)")
                    if eve_decrypted_attempt == bob_secret_password:
                        print("[ПРЕДУПРЕЖДЕНИЕ] Ева УСПЕШНО расшифровала данные! (Это не должно произойти)")
                    else:
                        print("[ОК] Ева не смогла расшифровать данные, несмотря на доступ к памяти.")
                else:
                    print("[ОШИБКА] Ева не смогла получить данные с сервера.")

                print("\n" + "*"*20 + " АЛИСА ПЫТАЕТСЯ ВМЕШАТЬСЯ " + "*"*20)
                alice_retrieved_encrypted_base64 = quantum_server.retrieve_client_data("Bob")
                if alice_retrieved_encrypted_base64:
                    alice_decrypted_attempt = self.decrypt_message(alice_retrieved_encrypted_base64, shared_key_AB)
                    print(f"Алиса: Получила данные Боба и расшифровала своим ключом: '{alice_decrypted_attempt}'")

            print("\n" + "*"*20 + " ПОВТОРНАЯ ПОПЫТКА QKD C ЕВОЙ " + "*"*20)
            shared_key_with_eve = self.find_secure_channel(self.num_bits, eve_active=True, max_attempts=5, qber_threshold=15)
            if not shared_key_with_eve:
                print("[OK] QKD-ключ не был установлен из-за активности Евы. Безопасность подтверждена.")
            else:
                print("[ПРЕДУПРЕЖДЕНИЕ] QKD-ключ был установлен, несмотря на Еву. (Это не должно произойти часто)")

class QuantumMemoryServer:
    def __init__(self, num_qudit_levels=10, memory_capacity_qudits=100):
        if num_qudit_levels < 2: raise ValueError("Number of qudit levels must be at least 2.")
        if num_qudit_levels > 256: print("Warning: num_qudit_levels > 256 might lead to inefficient encoding.")

        self.num_qudit_levels = num_qudit_levels
        self.memory_capacity = memory_capacity_qudits
        self.memory_slots = [qutip.fock(num_qudit_levels, 0) for _ in range(memory_capacity_qudits)]
        self.stored_data_metadata = {}
        print(f"\nQuantumMemoryServer запущен с {memory_capacity_qudits} осцилляторами (каждый до {num_qudit_levels} уровней).\n")

    def _encode_bytes_to_qudits(self, data_bytes):
        qudit_sequence = []
        for byte_val in data_bytes:
            num_qudits_per_byte = 0
            temp_val = 255
            while temp_val > 0:
                temp_val //= self.num_qudit_levels
                num_qudits_per_byte += 1
            if num_qudits_per_byte == 0: num_qudits_per_byte = 1

            digits = []
            val = byte_val
            if val == 0: digits = [0]
            else:
                while val > 0:
                    digits.append(val % self.num_qudit_levels)
                    val //= self.num_qudit_levels
                digits.reverse()

            while len(digits) < num_qudits_per_byte:
                digits.insert(0, 0)

            qudit_sequence.extend(digits)
        return qudit_sequence

    def _decode_qudits_to_bytes(self, qudit_sequence, original_bytes_len):
        decoded_bytes = bytearray()

        num_qudits_per_byte = 0
        temp_val = 255
        while temp_val > 0:
            temp_val //= self.num_qudit_levels
            num_qudits_per_byte += 1
        if num_qudits_per_byte == 0: num_qudits_per_byte = 1

        if len(qudit_sequence) % num_qudits_per_byte != 0:
             print(f"Warning: Qudit sequence length ({len(qudit_sequence)}) is not a multiple of qudits per byte ({num_qudits_per_byte}). Potential data corruption.")

        for i in range(0, len(qudit_sequence), num_qudits_per_byte):
            byte_val = 0
            for j in range(num_qudits_per_byte):
                if i + j < len(qudit_sequence):
                    byte_val += qudit_sequence[i+j] * (self.num_qudit_levels ** (num_qudits_per_byte - 1 - j))
            decoded_bytes.append(byte_val)
            if len(decoded_bytes) == original_bytes_len: break

        return bytes(decoded_bytes)

    def store_client_data(self, client_id, encrypted_base64_message):
        print(f"Сервер: Клиент '{client_id}' отправляет данные для хранения...")
        data_bytes = encrypted_base64_message.encode('ascii')
        qudit_sequence = self._encode_bytes_to_qudits(data_bytes)

        if len(qudit_sequence) > self.memory_capacity:
            print(f"[ОШИБКА Сервера] Недостаточно памяти для хранения данных клиента '{client_id}'. Требуется {len(qudit_sequence)} qudits, доступно {self.memory_capacity}.")
            return False

        start_idx = 0
        for i in range(len(qudit_sequence)):
            qudit = qudit_sequence[i]
            if qudit < 0 or qudit >= self.num_qudit_levels:
                print(f"[ОШИБКА Сервера] Недопустимое значение кудита: {qudit}. Должно быть в диапазоне [0, {self.num_qudit_levels-1}].")
                return False
            self.memory_slots[start_idx + i] = qutip.fock(self.num_qudit_levels, qudit)

        self.stored_data_metadata[client_id] = {
            'start_idx': start_idx,
            'num_qudits': len(qudit_sequence),
            'original_bytes_len': len(data_bytes)
        }
        print(f"Сервер: Данные клиента '{client_id}' ({len(qudit_sequence)} qudits) успешно сохранены в квантовую память.")
        return True

    def retrieve_client_data(self, client_id):
        print(f"Сервер: Клиент '{client_id}' запрашивает данные...")
        if client_id not in self.stored_data_metadata:
            print(f"[ОШИБКА Сервера] Данные для клиента '{client_id}' не найдены.")
            return None

        metadata = self.stored_data_metadata[client_id]
        start_idx = metadata['start_idx']
        num_qudits = metadata['num_qudits']
        original_bytes_len = metadata['original_bytes_len']

        read_qudit_sequence = []
        for i in range(num_qudits):
            oscillator_state = self.memory_slots[start_idx + i]
            read_qudit_sequence.append(int(qutip.expect(qutip.num(self.num_qudit_levels), oscillator_state)))

        data_bytes = self._decode_qudits_to_bytes(read_qudit_sequence, original_bytes_len)
        encrypted_base64_message = data_bytes.decode('ascii')
        print(f"Сервер: Данные клиента '{client_id}' успешно получены из квантовой памяти.")
        return encrypted_base64_message
