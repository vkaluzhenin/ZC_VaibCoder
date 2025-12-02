#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генератор PDF из CSV и HTML-шаблонов
Поддерживает кириллицу и интерактивный выбор файлов
"""

import os
import sys
import csv
import re
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional


try:
    from weasyprint import HTML
except ImportError:
    print("Ошибка: WeasyPrint не установлен.")
    print("Установите его командой: pip install weasyprint")
    sys.exit(1)


def find_files_by_extension(directory: Path, extension: str) -> List[Path]:
    """
    Находит все файлы с указанным расширением в директории и поддиректориях.
    
    Args:
        directory: Директория для поиска
        extension: Расширение файла (например, '.csv' или '.html')
    
    Returns:
        Список путей к найденным файлам
    """
    files = []
    for root, dirs, filenames in os.walk(directory):
        for filename in filenames:
            if filename.lower().endswith(extension.lower()):
                files.append(Path(root) / filename)
    return sorted(files)


def select_file_interactive(files: List[Path], file_type: str) -> Optional[Path]:
    """
    Интерактивный выбор файла из списка.
    
    Args:
        files: Список путей к файлам
        file_type: Тип файла для отображения ('CSV' или 'HTML')
    
    Returns:
        Выбранный путь к файлу или None, если выбор отменен
    """
    if not files:
        print(f"\n❌ {file_type}-файлы не найдены в текущей директории и поддиректориях.")
        return None
    
    print(f"\n📁 Найдено {file_type}-файлов: {len(files)}")
    print("-" * 70)
    
    for idx, file_path in enumerate(files, 1):
        # Показываем относительный путь для удобства
        try:
            rel_path = file_path.relative_to(Path.cwd())
        except ValueError:
            rel_path = file_path
        
        print(f"{idx}. {rel_path}")
    
    print("-" * 70)
    print(f"0. Отмена")
    
    while True:
        try:
            choice = input(f"\nВыберите {file_type}-файл (1-{len(files)} или 0 для отмены): ").strip()
            
            if choice == "0":
                return None
            
            choice_num = int(choice)
            if 1 <= choice_num <= len(files):
                selected_file = files[choice_num - 1]
                print(f"✓ Выбран: {selected_file}")
                return selected_file
            else:
                print(f"⚠ Неверный выбор. Введите число от 1 до {len(files)} или 0 для отмены.")
        except ValueError:
            print("⚠ Введите корректное число.")
        except KeyboardInterrupt:
            print("\n\nОперация отменена пользователем.")
            return None


def read_csv_with_cyrillic(csv_path: Path) -> List[Dict[str, str]]:
    """
    Читает CSV-файл с поддержкой кириллицы.
    
    Args:
        csv_path: Путь к CSV-файлу
    
    Returns:
        Список словарей, где каждый словарь представляет строку CSV
    """
    rows = []
    
    # Пробуем разные кодировки для максимальной совместимости
    encodings = ['utf-8-sig', 'utf-8', 'cp1251', 'windows-1251']
    
    for encoding in encodings:
        try:
            with open(csv_path, 'r', encoding=encoding, newline='') as csvfile:
                # Автоопределение разделителя
                sample = csvfile.read(1024)
                csvfile.seek(0)
                sniffer = csv.Sniffer()
                delimiter = sniffer.sniff(sample).delimiter
                
                reader = csv.DictReader(csvfile, delimiter=delimiter)
                rows = [row for row in reader]
                
                if rows:
                    print(f"✓ CSV успешно прочитан (кодировка: {encoding}, разделитель: '{delimiter}')")
                    print(f"✓ Найдено строк: {len(rows)}")
                    if rows:
                        print(f"✓ Колонки: {', '.join(rows[0].keys())}")
                    return rows
        except (UnicodeDecodeError, Exception) as e:
            continue
    
    raise ValueError(f"Не удалось прочитать CSV-файл с поддерживаемыми кодировками: {encodings}")


def load_html_template(template_path: Path) -> str:
    """
    Загружает HTML-шаблон с поддержкой кириллицы.
    
    Args:
        template_path: Путь к HTML-шаблону
    
    Returns:
        Содержимое шаблона как строка
    """
    encodings = ['utf-8', 'utf-8-sig', 'cp1251', 'windows-1251']
    
    for encoding in encodings:
        try:
            with open(template_path, 'r', encoding=encoding) as f:
                content = f.read()
                print(f"✓ HTML-шаблон загружен (кодировка: {encoding})")
                return content
        except (UnicodeDecodeError, Exception):
            continue
    
    raise ValueError(f"Не удалось прочитать HTML-шаблон с поддерживаемыми кодировками: {encodings}")


def calculate_fields(data: Dict[str, str], record_number: int, total_records: int) -> Dict[str, str]:
    """
    Вычисляет дополнительные поля на основе данных CSV.
    
    Args:
        data: Исходные данные из CSV
        record_number: Номер текущей записи (начинается с 1)
        total_records: Общее количество записей
    
    Returns:
        Расширенный словарь с вычисленными полями
    """
    # Создаем копию данных
    result = data.copy()
    
    # Добавляем метаданные
    result['record_number'] = str(record_number)
    result['total_records'] = str(total_records)
    result['generation_date'] = datetime.now().strftime('%d.%m.%Y %H:%M')
    
    # Вычисляем финансовые поля
    try:
        # Парсим цену (убираем пробелы и нечисловые символы кроме точки и запятой)
        price_str = str(data.get('price', '0')).strip().replace(' ', '').replace(',', '.')
        # Убираем все кроме цифр и точки
        price_str = re.sub(r'[^\d.]', '', price_str)
        price = float(price_str) if price_str else 0.0
        
        # Парсим количество
        qty_str = str(data.get('qty', '0')).strip()
        qty_str = re.sub(r'[^\d]', '', qty_str)
        qty = int(qty_str) if qty_str else 0
        
        # Вычисляем суммы
        subtotal = price * qty
        vat = subtotal * 0.2  # НДС 20%
        total = subtotal + vat
        
        # Форматируем числа для отображения (русский формат: пробелы для тысяч, запятая для дробей)
        def format_currency(value):
            """Форматирует число в валютный формат (123 456,78)"""
            # Округляем до 2 знаков после запятой
            value = round(value, 2)
            # Разделяем на целую и дробную части
            integer_part = int(value)
            fractional_part = int(round((value - integer_part) * 100))
            
            # Форматируем целую часть с пробелами для тысяч
            integer_str = f"{integer_part:,}".replace(',', ' ')
            
            # Возвращаем с дробной частью
            return f"{integer_str},{fractional_part:02d}"
        
        result['subtotal'] = format_currency(subtotal)
        result['vat'] = format_currency(vat)
        result['total'] = format_currency(total)
        
        # Также сохраняем числовые значения для возможного использования
        result['price_numeric'] = str(price)
        result['qty_numeric'] = str(qty)
        result['subtotal_numeric'] = str(subtotal)
        result['vat_numeric'] = str(vat)
        result['total_numeric'] = str(total)
        
    except (ValueError, TypeError) as e:
        # Если не удалось вычислить, используем значения по умолчанию
        result['subtotal'] = '0,00'
        result['vat'] = '0,00'
        result['total'] = '0,00'
    
    return result


def substitute_template(template: str, data: Dict[str, str]) -> str:
    """
    Подставляет данные в HTML-шаблон.
    Поддерживает формат {{ключ}} (двойные фигурные скобки) и {ключ} (одинарные).
    Безопасно обрабатывает фигурные скобки в данных.
    
    Args:
        template: HTML-шаблон с плейсхолдерами
        data: Словарь с данными для подстановки
    
    Returns:
        HTML с подставленными данными
    """
    result = template
    
    # Сначала обрабатываем двойные фигурные скобки {{key}}
    # Это стандартный синтаксис для некоторых шаблонизаторов
    for key, value in data.items():
        if value is None:
            value = ''
        else:
            value = str(value)
        
        # Заменяем двойные фигурные скобки {{key}}
        double_placeholder = f"{{{{{key}}}}}"
        if double_placeholder in result:
            result = result.replace(double_placeholder, value)
    
    # Затем обрабатываем одинарные фигурные скобки {key}
    for key, value in data.items():
        if value is None:
            value = ''
        else:
            value = str(value)
        
        # Заменяем одинарные фигурные скобки {key}
        single_placeholder = f"{{{key}}}"
        if single_placeholder in result:
            result = result.replace(single_placeholder, value)
    
    # Обрабатываем случаи, когда в шаблоне остались плейсхолдеры без соответствующих данных
    # Заменяем их на пустую строку (обрабатываем и двойные, и одинарные скобки)
    remaining_double = re.findall(r'\{\{([^}]+)\}\}', result)
    for placeholder_key in remaining_double:
        if placeholder_key not in data:
            result = result.replace(f"{{{{{placeholder_key}}}}}", "")
    
    remaining_single = re.findall(r'\{([^}]+)\}', result)
    for placeholder_key in remaining_single:
        # Пропускаем уже обработанные двойные скобки и пустые значения
        if placeholder_key not in data and placeholder_key.strip():
            result = result.replace(f"{{{placeholder_key}}}", "")
    
    return result


def generate_pdf(html_content: str, output_path: Path) -> bool:
    """
    Генерирует PDF из HTML-контента с поддержкой кириллицы.
    
    Args:
        html_content: HTML-контент
        output_path: Путь для сохранения PDF
    
    Returns:
        True если успешно, False в противном случае
    """
    try:
        # Убеждаемся, что в HTML есть правильная кодировка и стили для кириллицы
        if '<meta charset' not in html_content.lower() and '<meta http-equiv' not in html_content.lower():
            # Добавляем мета-тег кодировки если его нет
            html_content = html_content.replace('<head>', '<head>\n<meta charset="UTF-8">', 1)
            if '<head>' not in html_content:
                html_content = '<head>\n<meta charset="UTF-8">\n</head>\n' + html_content
        
        # Добавляем базовые стили для таблиц, если их нет
        if '<style' not in html_content.lower():
            table_styles = """
<style>
    body {
        font-family: 'DejaVu Sans', 'Arial Unicode MS', 'Arial', sans-serif;
    }
    table {
        width: 100%;
        border-collapse: collapse;
        margin: 10px 0;
    }
    th, td {
        border: 1px solid #000;
        padding: 8px;
        text-align: left;
        word-wrap: break-word;
        overflow-wrap: break-word;
    }
    th {
        background-color: #f0f0f0;
        font-weight: bold;
        text-align: center;
    }
    td {
        vertical-align: top;
    }
    tr:nth-child(even) {
        background-color: #f9f9f9;
    }
    .long-text {
        word-wrap: break-word;
        max-width: 300px;
    }
    .break-word {
        word-wrap: break-word;
        overflow-wrap: break-word;
        word-break: break-word;
        max-width: 300px;
    }
    .text-left {
        text-align: left;
    }
    .text-right {
        text-align: right;
    }
    .text-center {
        text-align: center;
    }
</style>
"""
            if '</head>' in html_content:
                html_content = html_content.replace('</head>', table_styles + '</head>', 1)
            elif '<body' in html_content:
                html_content = html_content.replace('<body>', '<head>' + table_styles + '</head>\n<body>', 1)
            else:
                html_content = '<head>' + table_styles + '</head>\n' + html_content
        
        HTML(string=html_content).write_pdf(output_path)
        return True
    except Exception as e:
        print(f"❌ Ошибка при создании PDF: {e}")
        return False


def open_pdf(pdf_path: Path) -> None:
    """
    Автоматически открывает PDF-файл в зависимости от операционной системы.
    
    Args:
        pdf_path: Путь к PDF-файлу
    """
    system = platform.system()
    
    try:
        if system == 'Windows':
            os.startfile(str(pdf_path))
        elif system == 'Darwin':  # macOS
            subprocess.run(['open', str(pdf_path)], check=True)
        elif system == 'Linux':
            subprocess.run(['xdg-open', str(pdf_path)], check=True)
        else:
            print(f"⚠ Автоматическое открытие PDF не поддерживается для {system}")
            print(f"   Откройте файл вручную: {pdf_path}")
    except Exception as e:
        print(f"⚠ Не удалось автоматически открыть PDF: {e}")
        print(f"   Откройте файл вручную: {pdf_path}")


def main():
    """Основная функция программы."""
    print("=" * 70)
    print("📄 ГЕНЕРАТОР PDF ИЗ CSV И HTML-ШАБЛОНОВ")
    print("=" * 70)
    print(f"Текущая директория: {Path.cwd()}\n")
    
    # Шаг 1: Выбор CSV-файла
    csv_files = find_files_by_extension(Path.cwd(), '.csv')
    csv_path = select_file_interactive(csv_files, 'CSV')
    
    if csv_path is None:
        print("\n❌ CSV-файл не выбран. Выход.")
        return
    
    # Шаг 2: Выбор HTML-шаблона
    html_files = find_files_by_extension(Path.cwd(), '.html')
    template_path = select_file_interactive(html_files, 'HTML')
    
    if template_path is None:
        print("\n❌ HTML-шаблон не выбран. Выход.")
        return
    
    # Шаг 3: Чтение CSV
    try:
        csv_data = read_csv_with_cyrillic(csv_path)
    except Exception as e:
        print(f"\n❌ Ошибка при чтении CSV: {e}")
        return
    
    if not csv_data:
        print("\n❌ CSV-файл пуст или не содержит данных.")
        return
    
    # Шаг 4: Загрузка HTML-шаблона
    try:
        html_template = load_html_template(template_path)
    except Exception as e:
        print(f"\n❌ Ошибка при загрузке HTML-шаблона: {e}")
        return
    
    # Шаг 5: Создание директории для PDF-файлов
    output_dir = Path.cwd() / 'generated_pdfs'
    output_dir.mkdir(exist_ok=True)
    print(f"\n📁 PDF-файлы будут сохранены в: {output_dir}")
    
    # Шаг 6: Генерация PDF для каждой строки CSV
    print("\n🔄 Начинаю генерацию PDF-файлов...")
    print("-" * 70)
    
    first_pdf_path = None
    success_count = 0
    error_count = 0
    
    for idx, row in enumerate(csv_data, 1):
        try:
            # Вычисляем дополнительные поля (суммы, даты, номера записей)
            extended_data = calculate_fields(row, idx, len(csv_data))
            
            # Подстановка данных в шаблон
            html_content = substitute_template(html_template, extended_data)
            
            # Создание имени файла (используем первый столбец или индекс)
            filename_base = list(row.values())[0] if row else f"record_{idx}"
            # Очистка имени файла от недопустимых символов для Windows
            # Недопустимые символы: < > : " / \ | ? *
            invalid_chars = '<>:"/\\|?*'
            filename_base = ''.join(c if c not in invalid_chars else '_' for c in str(filename_base))
            # Удаляем пробелы в начале и конце, заменяем множественные пробелы на один
            filename_base = re.sub(r'\s+', ' ', filename_base).strip()
            # Ограничиваем длину имени файла (Windows: до 255 символов для пути, оставляем место для расширения и индекса)
            if len(filename_base) > 200:
                filename_base = filename_base[:200]
            if not filename_base:
                filename_base = f"record_{idx}"
            
            pdf_filename = f"{filename_base}_{idx}.pdf"
            pdf_path = output_dir / pdf_filename
            
            # Генерация PDF
            if generate_pdf(html_content, pdf_path):
                print(f"✓ [{idx}/{len(csv_data)}] Создан: {pdf_filename}")
                success_count += 1
                if first_pdf_path is None:
                    first_pdf_path = pdf_path
            else:
                print(f"❌ [{idx}/{len(csv_data)}] Ошибка при создании: {pdf_filename}")
                error_count += 1
                
        except Exception as e:
            print(f"❌ [{idx}/{len(csv_data)}] Ошибка: {e}")
            error_count += 1
    
    # Шаг 7: Итоги и открытие первого PDF
    print("-" * 70)
    print(f"\n✅ Готово!")
    print(f"   Успешно создано: {success_count}")
    if error_count > 0:
        print(f"   Ошибок: {error_count}")
    
    if first_pdf_path and first_pdf_path.exists():
        print(f"\n📂 Открываю первый созданный PDF...")
        open_pdf(first_pdf_path)
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠ Операция прервана пользователем.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

