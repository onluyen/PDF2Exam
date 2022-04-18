from collections import defaultdict
import fitz
import json
import re
import copy
import os
import base64
from pathlib import Path

def extract_pdf(file, path_root_output):
    """Main function to extract pdf

    Args:
        file (str): link to the file
        path_root_output (str): link to the output's file

    Returns:
        list: list containing coordinates and base 64 image of questions's content, answer options, question titles, page, and correct_options
    """
    doc = fitz.open(file)
    n_page = doc.page_count
    num_q = 1
    questions = []
    explains = []
    correct_answers = {}
    answers_options = []
    append_reading = False
    type_flag = 0
    # -- flag ----
    # --- 0: question
    # --- 2: essay (essays are questions without answer options)
    # --- 4: explain
    # --- 99: end of processing questions and answers
    
    # check first question to get ascender_descender_option
    answers_options = get_question_0(doc[0])

    # -- get ascender_descender_option
    # use ascender_descender_option to identify the correct answer option title 
    # when there are more than four titles in one question
    ascender_descender_option = []
    if len(answers_options) != 0:
        ascender_descender_option = get_ascender_descender_option(answers_options) 

    # if first question does not have answer options
    # default all question are essay type
    if len(ascender_descender_option) == 0:
        type_flag = 2

    # freeing the memory used
    del answers_options
    
    # there are two phases to extract pdf:
    # 1st phase: go through all pages and find all information. 
    # 2nd phase: from the information in 1st part, check if information is correct and create images
    
    # 1st phase: go through all pages and find all information
    for i_page in range(n_page):    
        blocks = get_json_page(doc[i_page], type_flag, i_page)
        if len(blocks) == 0:
            break

        # --- case questions (multiple choice and essay type) ---------------------------
        if type_flag == 0 or type_flag == 2:  
            data = perform_traversal_questions_set(doc[i_page], blocks, num_q, explains, append_reading)
        # --- case explains ---------------------------
        elif type_flag == 4:
            data = process_explain(blocks, num_q)
            num_q = data[4]
            explains.append([i_page, data[2]])
        # --- case correct answer ---------------------------
        elif type_flag == 99:
            data = process_correct_answer(blocks)

        # order of list's returning values 
        # -- 0: questions
        # -- 1: answers_options
        # -- 2: explains
        # -- 3: correct answers 
        # -- 4: num_q
        # -- 5: type_flag
        # -- 6: append_reading
        
        if type_flag != 4:
            if len(data[0]) > 0:
                if len(data[1]) > 0: 
                    questions.append([i_page, data[0], data[1]])
                else:
                    questions.append([i_page, data[0], {}])
            if len(data[2]) > 0:
                explains.append([i_page, data[2]])
            if len(data[3]) > 0:
                correct_answers = data[3]
            if len(data) > 4:
                num_q = data[4]
            if len(data) > 5:
                type_flag = data[5]
            if len(data) > 6:
                append_reading = data[6]
    
    coor_x = [1000, 0]
    
    coor_explains_result = {}
    if len(explains) > 0: # pdf has explanation
        coor_explains_result = process_explain_base64(explains, coor_x, doc, path_root_output)
    
    # question 0 includes extra information (date, name of test, etc) before question 1 is found
    # no need to create image of question 0
    questions[0][1].pop('question_0', None)
    
    # 2nd phase: process information after collecting it from 1st phase
    data_question = process_question_and_answers(questions, doc, coor_x, ascender_descender_option)

    doc.close()

    return {
        "questions": data_question[0],
        "answers": data_question[1],
        "titles": data_question[2],
        "correct_options": correct_answers,
        "explains": coor_explains_result
    }

def perform_traversal_questions_set(page, blocks, num_q, explain_previous, append_reading):
    """Collect information of questions 

    Args:
        page (fitz.Page): information of page
        blocks (list): list of page's blocks
        num_q (int): question's number
        explain_previous (list): list of previous explanation
        flag_answers_options (bool):  check if answer option should be looked for

    Returns:
        list: list containing returning type, questions, number of questions, explanation and answer options
    """
    # -- params question --
    questions = {}
    # -- params answer --
    answers_options = {}
    # -- params explanation --
    explains = {}

    flag_explain_in_question = False
    len_explains = len(explain_previous)
    if len_explains > 0 and f'question_{num_q - 1}' in explain_previous[len_explains - 1][1]:
        flag_explain_in_question = True
        
    page_height = page.mediabox[3]
    first_essay = False
    type_flag = 0

    for block in blocks:                    
        # --- mediabox out of rect ----
        if check_mediabox_block(block) or check_mediabox_height(block, page_height):    
            continue
        
        # -- check lines in block --
        if "lines" in block:
            for line in block['lines']:
                text_spans = get_text_spans(line)
                
                # -------Omit the line is empty -----------------------
                if text_spans.strip() == "" and line['bbox'][2] - line['bbox'][0] < 4:
                    continue
                # ---------------------- END OF PROCESSING QUESTION ---------------------------------
                if check_end_text(text_spans) or check_correct_answer_text(text_spans):
                    data = process_stop_questions(remove_item_in_blocks(blocks, block, line, True))
                    data[0] = questions
                    data[1] = answers_options
                    if len(data[2]) > 0:
                        explains.update(data[2])
                    data[2] = explains
                    return data 
                    
                # ---------------------- QUESTION TITLE ---------------------------------
                if check_question_title(text_spans, line):
                    
                    # the reading passage is attached to the question.
                    # num_q already adds one when the reading passage is found
                    # therefore, num_q needs to be deducted by 1 if the question is found
                    if append_reading:
                        num_q -= 1
                        append_reading = False
                        
                    if check_reading_passage(text_spans):
                        append_reading = True
                    
                    # --- case Question 1: A.
                    answers_options = check_question_contain_title_answer(answers_options, text_spans, line, num_q, page)
                    
                    if f'question_{num_q}' not in questions:
                        questions[f'question_{num_q}'] = line['bbox'] + [text_spans]
                    else:
                        questions[f'question_{num_q}'] = compare_coors_with_text(questions[f'question_{num_q}'][:5], line['bbox'] + [text_spans])

                    # -- get title question --
                    if not append_reading:
                        questions[f'question_{num_q}'].append(
                            get_title_question(line, page)) 

                    num_q += 1
                    flag_explain_in_question = False                    
                    first_essay = False
                    continue

                # ---------------------- ESSAY ---------------------------------
                elif check_essay_text(text_spans) or first_essay:
                    if text_spans.isspace() :
                        continue
                    
                    # skip line with essay text
                    if check_essay_text(text_spans):
                        first_essay = True
                        type_flag = 2
                        continue 

                    first_essay = False
                    num_q += 1

                    questions[f'question_{num_q - 1}'] = line['bbox'] + [text_spans]
                    continue

                # ---------------------- EXPLAIN IN QUESTION ---------------------------------
                if check_explain_text(text_spans):
                    flag_explain_in_question = True
                    explains[f'question_{num_q - 1}'] = line['bbox'] + \
                        [text_spans]
                    continue

                # --------------------- OPTION ANSWERS ---------------------------------------
                if not append_reading and type_flag != 2:
                    answers_options = check_answer_option(page,
                        num_q, flag_explain_in_question, line, text_spans, answers_options)
                
                # --------------------- QUESTIONS ---------------------------------------
                if flag_explain_in_question == False:
                    questions = merge_question(
                        line, questions, num_q, text_spans, answers_options)
                else:
                    explains = merge_question(
                        line, explains, num_q, text_spans)
        else:
            if flag_explain_in_question == False:  
                if not explains:
                    questions = process_line_image(
                        questions, num_q, block)
                else:
                    data = process_line_image_with_answer_in_questions(
                        num_q, block, questions, explains)
                    questions = data[0]
                    explains = data[1]
            else:
                if bool(questions):
                    data = process_line_image_with_answer_in_questions(
                        num_q, block, explains, questions)
                    explains = data[0]
                    questions = data[1]
                else:
                    explains = process_line_image(
                        explains, num_q, block)
    
    return [questions, answers_options, explains, {}, num_q, 0, append_reading]


def process_question_and_answers(questions, doc, coor_x, ascender_descender_option):
    """Process answer option. Create image of questions and answers after gathering information previously

    Args:
        questions (dict): information of questions's coordinates and questions title's coordinates's coordinates and questions title's coordinates
        doc (fitz.doc): information of doc
        coor_x (list): list of explanation's max width
        ascender_descender_option (list): list containing ascender, descender and flag of answer option

    Returns:
        list: list containing coordinates and base 64 image of questions's content, answer options, question titles,
    """
    coor_titles = {}
    coor_questions_result = {}
    coor_answers_result = {}
    key_previous = ""
    for arr_question in questions:
        # arr_question[0] = page number
        # arr_question[1] = questions' overall coordinates and questions' titles coordinates
        # arr_question[2] = answers' coordinates
        if len(arr_question) < 3:	
            continue	
        n_page = arr_question[0]
        answers = []
        if len(arr_question) == 3:
            answers = arr_question[2]
        question = arr_question[1]
        
        for key in question:
            if len(question[key]) < 5:
                continue

            # get question number. starting from index of "_" till the end (exp:question_42)
            num_q = int(key[key.find("_") + 1:])
            # -- image --
            data_title = create_title_question(question[key], doc[n_page])
            if len(data_title) > 0:
                coor_titles[key] = data_title

            # ---- parse answers -----------------
            coor_answer_cover = []

            # check if question overlaps next question
            if f'question_{num_q + 1}' in question and question[f'question_{num_q}'][3] >= question[f'question_{num_q + 1}'][1]:
                question[f'question_{num_q}'][3] = question[f'question_{num_q + 1}'][1] - 0.5

            if f"{key}" in answers and len(ascender_descender_option) > 0:
                if not answers[key]:
                    coor_answers_result[key] = {"options": []}
                else:
                    # --- get key title answer ---
                    if f"{key}" not in coor_answers_result:
                        coor_answers_result[key] = {"options": []}
                    # --- search key title max ---  
                    answer_key = process_answer_titles(answers[key], ascender_descender_option)
                    
                    if check_answer_without_value(answer_key):
                        answers[key] = []
                    total_option = len(answers[key])
                    
                    if total_option != 0:
                        arr_key_title= []
                        for answer in answer_key:
                            arr_key_title.append(answer[0])
                        
                        # --- Process answer options --- 
                        if total_option == 4 and re.search(r"^(\s+)?D", arr_key_title[3][4]):
                            data_answer = check_column_and_get_answer_cover_four_options(
                                answers[key], doc[n_page], key, arr_key_title, n_page, question)
                        # Case total_option < 4: answer options are on two pages
                        elif total_option == 2:
                            data_answer = check_column_and_get_answer_cover_two_options(
                                answers[key], doc[n_page], key, arr_key_title, n_page, question)
                        elif total_option == 3:
                            data_answer = check_column_and_get_answer_cover_three_options(
                                answers[key], doc[n_page], key, arr_key_title, n_page, question)
                        elif total_option == 1 and len(answers[key]) != 0:
                            data_answer = get_ans_coor_one_and_two_options_one_column(
                                    answers[key], doc[n_page], key, arr_key_title, n_page, question)
                        else:
                            #if can not find answer option, set answer option to [] to avoid getting value from previous option
                            data_answer = [] 

                        if len(data_answer) > 0:
                            coor_answer_cover = data_answer[0]
                            if key in coor_answers_result:
                                coor_answers_result[key]['options'] += data_answer[1]
                            else:
                                coor_answers_result[key]['options'] = data_answer[1]       

                            # set end of question's height to start of answer coor cover's height   
                            if coor_answer_cover[1]  > question[f"{key}"][1]: # check same page
                                question[f"{key}"][3] =  coor_answer_cover[1]             

            if coor_x[0] > question[f"{key}"][0]:
                coor_x[0] = question[f"{key}"][0]
            else:
                question[f"{key}"][0] = coor_x[0]
                        
            if question[f"{key}"][4] == "":
                # --- case line is empty ---
                continue
            # ----- case question in two page ----
            if key_previous != key:
                key_previous = key
                coor_questions_result[key] = [{"page": n_page, "coor": get_base64_question(
                    doc[n_page], question[f"{key}"], coor_answer_cover, data_title)}]
            else:
                coor_questions_result[key].append({"page": n_page, "coor": get_base64_question(
                    doc[n_page], question[f"{key}"], coor_answer_cover, data_title)})
    
    return [coor_questions_result, coor_answers_result, coor_titles]

def get_text_lines(block):
    """Get the text of a block

    Args:
        block (list): information of block

    Returns:
        str: The text of a block
    """
    text_block = ""
    
    if block['type'] == 0:
        for line in block['lines']:
            text_block += get_text_spans(line)
    else:
        text_block = "image"
    
    return text_block.strip()

def get_text_spans(line):
    """Get the text of a line

    Args:
        line (dict): information of line

    Returns:
        str: The text of a line
    """
    text_block = ""
    
    for span in line['spans']:
        text_block += span['text']
    
    return text_block

def get_text_in_block(block, type_flag, check_page_num=False):
    """Check if block's text is footer or header 

    Args:
        block (dict): information of block
        check_page_num (bool, optional): check if block belongs to a page. Defaults to False.

    Returns:
        bool: Return true if block's text is footer or header 
    """
    text_block = get_text_lines(block).strip()

    if type_flag == 99 and re.search(r"Mã đề", text_block):
        return False
    pattern = r"((Trang|Page)+(\s+)?([0-9]\/[0-9]|[0-9]))|Mã đề"
    if check_page_num == True:
        pattern = r"((Trang|Page)+(\s+)?([0-9]\/[0-9]|[0-9]))|Mã đề|^(\s+)?([0-9]+)$"
    if text_block.strip() != "" and re.search(pattern, text_block.strip()):
        return True
    
    return False


def get_ascender_descender_option(answers_options):
    """Get the value of ascender, descender and flag of answer options

    Args:
        answers_options (dict): information of answer options

    Returns:
        list: list containing ascender, descender and flag of answer options
    """
    if "question_1" not in answers_options:
        return []

    # -- compare and get ascender_descender_option --
    arr_compare = {}
    ascender_descender_option = []

    for answers_option in answers_options["question_1"]:
        item = answers_option[0]
        option_text = item[4].replace(" ", "").replace(".", "")
        if len(arr_compare) == 0:
            arr_compare[option_text] = [1, item[4], item[5], item[6], item[7]]
        else:
            if option_text in arr_compare:
                arr_compare[option_text][0] += 1
            else:
                arr_compare[option_text] = [1, item[4], item[5], item[6], item[7]]
    
    for key in arr_compare:
        if arr_compare[key][0] == 1:
            # get ascender, color, flags (boldness of text)
            ascender_descender_option = [ arr_compare[key][2], arr_compare[key][3], arr_compare[key][4] ]
            break
    
    return ascender_descender_option

def get_base64_title(page, coors):
    """Get coordinates and base 64 image

    Args:
        page (fitz.Page): information of page
        coors (list): coordinates of x0, y0, x1, and y1

    Returns:
        list: list containing coordinates and base 64 image
    """
    data = ''
    # check coordinates are within page mediabox
    coors[2] = min(coors[2], page.mediabox[2])
    coors[3] = min(coors[3], page.mediabox[3])

    crop_box = fitz.Rect(coors[0], coors[1], coors[2], coors[3])
    if crop_box.isEmpty == False and crop_box.isInfinite == False:
        page.set_cropbox(crop_box)
        
        scale = 1.5
        zoom_x = scale # horizontal zoom
        zoom_y = scale  # vertical zoom
        mat = fitz.Matrix(zoom_x, zoom_y)  # zoom factor 1.5 in each dimension
        pix = page.get_pixmap(matrix=mat) 

        # pix = page.get_pixmap()
        data = ToDataBase64Image(pix)
        pix = None

    return coors + [data]

def DataBase64Image(base64Data):
    dataBase64 = f'data:image/png;base64,{base64Data}'
    dataBase64 = dataBase64.replace(
        "data:image/png;base64,b'", "data:image/png;base64,").replace("'", "")
    return dataBase64

def ToDataBase64Image(fitz_pix):
    base64Data = base64.b64encode(fitz_pix.pil_tobytes("png"))
    return DataBase64Image(base64Data)

def get_base64_question(page, coors, coor_answer_cover, data_title):
    """Get base 64 image of question. Set answer and question's title to white 

    Args:
        page (fitz.Page): information of page
        coors (list): coordinates of entire questions
        coor_answer_cover (list, optional): list containing the smallest x0 and y0, and largest x1 and y1 of answers. 
        data_title (list, optional): list containing the coordinates of question title. 

    Returns:
        list: list containing base 64 image of question
    """ 
    data = ''
    # guarantee coordinates are within page mediabox
    coors[2] = min(coors[2], page.mediabox[2])
    coors[3] = min(coors[3], page.mediabox[3])

    crop_box = fitz.Rect(coors[0], coors[1], coors[2], coors[3])
    if crop_box.isEmpty == False and crop_box.isInfinite == False:
        page.set_cropbox(crop_box)

        scale = 1.5
        zoom_x = scale # horizontal zoom
        zoom_y = scale # vertical zoom
        mat = fitz.Matrix(zoom_x, zoom_y)  
        pix = page.get_pixmap(matrix=mat)  # use 'mat' instead of the identity matrix

        # case question 1: A. 
        # delete all question
        if len(coor_answer_cover) > 0 and coor_answer_cover[1] == coors[1]:
            pix = delete_white_coor_section(pix, coors, scale)

        # pix = delete_white_coor(pix, coor_answer_cover, coors, scale)
        # set question title to white
        pix = delete_white_coor(pix, data_title, coors, scale)
        
        data = ToDataBase64Image(pix)
        pix = None
    
    coors[4] = data
    if len(coors) == 6:
        del coors[5]
    
    return coors

def delete_white_coor_section(pix, coor, scale):
    """Set color or given coordinates to white

    Args:
        pix (fitz.Pixmap): pix 
        coor (list): coordinates of x0, y0, x1, and y1 of outer part
        scale (int): scale number
    Returns:
        pix: pix
    """
    if coor:
        pix.set_rect(
                fitz.Rect(
                    0,
                    0,
                    coor[2]*scale,
                    coor[3]*scale
                ),
                (255, 255, 255)
            )
    return pix
    
def delete_white_coor(pix, coor, coor_main, scale):
    """Set color of outer part that was not included in inner part to white

    Args:
        pix (fitz.Pixmap): pix 
        coor (list): coordinates of x0, y0, x1, and y1 of outer part
        coor_main (list): coordinates of x0, y0, x1, and y1 of inner part
        scale (int): scale number
    Returns:
        pix: pix
    """
    
    if len(coor) >= 3 and len(coor_main) >= 1:
        pix.set_rect(
            fitz.Rect(
                (coor[0]*scale - coor_main[0]*scale),
                (coor[1]*scale - coor_main[1]*scale),
                (coor[2]*scale - coor_main[0]*scale),
                (coor[3]*scale - coor_main[1]*scale)
            ),
            (255, 255, 255)
        )

    return pix    

def create_title_question(question, page):
    """Get coordinate and create base 64 image of question title 

    Args:
        question (list): information of question
        page (fitz.Page): information of page

    Returns:
        list: list containing base 64 image of question
    """
    if len(question) == 6:
        coor_title = question[5]
        if len(coor_title) == 0:
            return []

        del coor_title[4:6]
        return get_base64_title(page, coor_title)
    
    return []

def check_column_and_get_answer_cover_three_options(answers, page, key, arr_key_title, n_page, question):
    """Case where there are three answer options. Get the number of column and get the coordinate of box covering all answers options and list of answer options. 
    Args:
        answers (list): list of answer option's coordinates
        page (fitz.Page): information of page
        key (str): question's number (for example: question_1)
        arr_key_title (list): list of answer option title's coordinates
        n_page (int): page's number

    Returns:
        list: List containing coordinate of box covering all answers options and list of answer options. 
    """
    # only 1 column answer has case of three options
    return get_ans_coor_three_options_one_column(answers, page, key, arr_key_title, n_page, question)

    
def check_column_and_get_answer_cover_two_options(answers, page, key, arr_key_title, n_page, question):
    """Case where there are two answer options. Get the number of column and get the coordinate of box covering all answers options and list of answer options. 
    Args:
        answers (list): list of answer option's coordinates
        page (fitz.Page): information of page
        key (str): question's number (for example: question_1)
        arr_key_title (list): list of answer option title's coordinates
        n_page (int): page's number

    Returns:
        list: List containing coordinate of box covering all answers options and list of answer options. 
    """
    column_answer = check_column_answers_two_options(arr_key_title)
    if column_answer == 2:
        return get_ans_coor_two_options_two_column(answers, page, key, arr_key_title, n_page, question)
    else:
        return get_ans_coor_one_and_two_options_one_column(answers, page, key, arr_key_title, n_page, question)

def get_ans_coor_one_and_two_options_one_column(answers, page, key, arr_key_title, n_page, question):
    """Case where there 1 answer or 2 answer options in one column. Get the number of column and get the coordinate of box covering all answers options and list of answer options. 
    Args:
        answers (list): list of answer option's coordinates
        page (fitz.Page): information of page
        key (str): question's number (for example: question_1)
        arr_key_title (list): list of answer option title's coordinates
        n_page (int): page's number

    Returns:
        list: List containing coordinate of box covering all answers options and list of answer options. 
    """
    data = get_coor_answers(answers, arr_key_title, question, key)
    coor_answers = data[0]
    coor_answers_cover = data[1]
    coor_answers = smooth_one_column_answers_two_options(
        coor_answers, coor_answers_cover, arr_key_title)
    options = create_image_answers(page, arr_key_title, coor_answers, n_page, key, question)
    
    return [coor_answers_cover, options]

def get_ans_coor_three_options_one_column(answers, page, key, arr_key_title, n_page, question):
    """Case where there are three answer options in one column.Get the coordinate of box covering all answers options and list of answer options. 
    Args:
        answers (list): list of answer option's coordinates
        page (fitz.Page): information of page
        key (str): question's number (for example: question_1)
        arr_key_title (list): list of answer option title's coordinates
        n_page (int): page's number

    Returns:
        list: List containing coordinate of box covering all answers options and list of answer options. 
    """
    data = get_coor_answers(answers, arr_key_title, question, key)
    coor_answers = data[0]
    coor_answers_cover = data[1]
    
    coor_answers = smooth_one_column_answers_three_options(
        coor_answers, coor_answers_cover, arr_key_title)
    
    options = create_image_answers(
        page, arr_key_title, coor_answers, n_page, key, question)
    
    return [coor_answers_cover, options]


def smooth_one_column_answers_two_options(coor, coor_cover, arr_key_title):
    """Adjust coordinates of answer options to cover the content of answer options

    Args:
        coor (list): list of answer option coordinates
        coor_cover (list): list of box covering answer options
        arr_key_title (list): list of answer options' titles' coordinates

    Returns:
        list: list containing the coordinates of answer options' content
    """
    len_coor = len(coor)
    if len_coor == 3 and coor[1][3] > coor[2][1]:
        coor[1][3] = coor[2][1] 
        coor[2][2] = coor_cover[2]
    if len_coor >= 2 and coor[0][3] > coor[1][1]:
        coor[0][3] = coor[1][1] 
        coor[1][2] = coor_cover[2]
    coor[0][2] = coor_cover[2]
    
    return get_answer_content(coor, arr_key_title)

def get_ans_coor_two_options_two_column(answers, page, key, arr_key_title, n_page, question):
    """Case where there are two answer options in two column. Get the coordinate of box covering all answers options and list of answer options. 
    Args:
        answers (list): list of answer option's coordinates
        page (fitz.Page): information of page
        key (str): question's number (for example: question_1)
        arr_key_title (list): list of answer option title's coordinates
        n_page (int): page's number

    Returns:
        list: List containing coordinate of box covering all answers options and list of answer options. 
    """
    data = get_coor_answers(answers, arr_key_title, question, key)
    coor_answers = data[0]
    coor_answers_cover = data[1]

    coor_answers = smooth_two_column_answers_two_options(
        coor_answers, coor_answers_cover, arr_key_title)
    options = create_image_answers(
        page, arr_key_title, coor_answers, n_page, key, question)
    
    return [coor_answers_cover, options]

def check_column_and_get_answer_cover_four_options(answers, page, key, arr_key_title, n_page, question):
    """Case where there are four answer options. Get the number of column and get the coordinate of box covering all answers options and list of answer options. 
    Args:
        answers (list): list of answer option's coordinates
        page (fitz.Page): information of page
        key (str): question's number (for example: question_1)
        arr_key_title (list): list of answer option title's coordinates
        n_page (int): page's number

    Returns:
        list: List containing coordinate of box covering all answers options and list of answer options. 
    """
    column_answer = check_column_answers_four_options(arr_key_title)
    coor_answer_cover = []
    if column_answer == 4:
        coor_answer_cover = get_ans_coor_four_options_four_column(
            answers, page, key, arr_key_title, n_page, question)
    elif column_answer == 2:
        coor_answer_cover = get_ans_coor_four_options_two_column(
            answers, page, key, arr_key_title, n_page, question)
    elif column_answer == 1:
        coor_answer_cover = get_ans_coor_four_options_one_column(
            answers, page, key, arr_key_title, n_page, question)
    
    return coor_answer_cover

def get_ans_coor_four_options_one_column(answers, page, key, arr_key_title, n_page, question):
    """Case where there are four answer options in one column.Get the coordinate of box covering all answers options and list of answer options. 
    Args:
        answers (list): list of answer option's coordinates
        page (fitz.Page): information of page
        key (str): question's number (for example: question_1)
        arr_key_title (list): list of answer option title's coordinates
        n_page (int): page's number

    Returns:
        list: List containing coordinate of box covering all answers options and list of answer options. 
    """
    data = get_coor_answers(answers, arr_key_title, question, key)
    coor_answers = data[0]
    coor_answers_cover = data[1]
    
    coor_answers = smooth_one_column_answers(
        coor_answers, coor_answers_cover, arr_key_title)
    options = create_image_answers(
        page, arr_key_title, coor_answers, n_page, key, question)
    return [coor_answers_cover, options]

def get_ans_coor_four_options_four_column(answers, page, key, arr_key_title, n_page, question):
    """Case where there are four answer options in four column.Get the coordinate of box covering all answers options and list of answer options. 
    Args:
        answers (list): list of answer option's coordinates
        page (fitz.Page): information of page
        key (str): question's number (for example: question_1)
        arr_key_title (list): list of answer option title's coordinates
        n_page (int): page's number

    Returns:
        list: List containing coordinate of box covering all answers options and list of answer options. 
    """
    data = get_coor_answers(answers, arr_key_title, question, key)
    coor_answers = data[0]
    coor_answers_cover = data[1]
    coor_c = copy.deepcopy(arr_key_title)
    
    coor_answers = smooth_four_column_answers(
        coor_answers, coor_answers_cover, coor_c)
    
    options = create_image_answers(
        page, arr_key_title, coor_answers, n_page, key, question)
    
    return [coor_answers_cover, options]


def get_ans_coor_four_options_two_column(answers, page, key, arr_key_title, n_page, question):
    """Case where there are four answer options in two column.Get the coordinate of box covering all answers options and list of answer options. 
    Args:
        answers (list): list of answer option's coordinates
        page (fitz.Page): information of page
        key (str): question's number (for example: question_1)
        arr_key_title (list): list of answer option title's coordinates
        n_page (int): page's number

    Returns:
        list: List containing coordinate of box covering all answers options and list of answer options. 
    """
    # -- case: 2 column --
    coor_answers_cover = [[2000, 2000, 0, 0], [2000, 2000, 0, 0]]
    coor_answers = []

    # case: value read before answer title
    if answers[0][0][0] == answers[0][1][0]:
        coor_answers_cover = [[2000, 2000, page.mediabox[2], 0], [2000, 2000, page.mediabox[2], 0]]

    for i in range(0, len(answers)):
        answer = answers[i]
        # -- delete item title --
        answer.pop(0)
        # -- option value -----
        if len(answer) > 0:
            coor_answers.append(answer[0])
            if 0 <= i <= 1:
                coor_answers_cover[0] = compare_coors(
                    coor_answers_cover[0], answer[0])
            else:
                coor_answers_cover[1] = compare_coors(
                    coor_answers_cover[1], answer[0])
                
    coor_answers = smooth_two_column_answers(
        coor_answers, coor_answers_cover, arr_key_title, question, key)

    options = create_image_answers(
        page, arr_key_title, coor_answers, n_page, key, question)
    
    return [compare_coors(coor_answers_cover[0], coor_answers_cover[1]), options]

def create_image_answers(page, arr_key_title, coor_answers, n_page, key, question = None):
    """Create base 64 image of answer option's title and content

    Args:
        page (fitz.Page): information of page
        arr_key_title (list): list of answer option title's coordinates
        coor_answers (list): list of answer option's coordinates
        n_page (int): page's number
        key (str): question's number

    Returns:
        list: list containing answer options' coordinates
    """
    options = []
    for i in range(0, len(arr_key_title)):
        text_op = re.sub(r"[\s|\.]", "", arr_key_title[i][4])
        if len(text_op) > 1:
            arr_key_title[i][2] = arr_key_title[i][0] + 16
            coor_answers[i][0] = arr_key_title[i][2]
        title_option = get_base64_title(page, arr_key_title[i])
        total = len(title_option)
        del title_option[total - 5:total-1]

        if (coor_answers[i][0] == coor_answers[i][2]):
            coor_answers[i][2] = question[key][2]

        # delete answer option content
        if len(coor_answers[i]) == 5:
            del coor_answers[i][-1]

        options.append(title_option + get_base64_title(page,
                       coor_answers[i]) + [n_page])
            
    return options


def get_coor_answers(answers, arr_key_title, question, key):
    """Get coordinates of answer option and box covering all answer option

    Args:
        answers (list): list of question coordinates
        arr_key_title (list): list of answer options' titles' coordinates

    Returns:
        list: list containing coordinates of answer option and box covering all answer option
    """
    coor_answers_cover = [2000, 2000, 0, 0]
    coor_answers = []

    for i in range(len(answers)):
        answer = answers[i]
        # -- delete item title --
        answer.pop(0)
        # -- option value -----
        if len(answer) > 0:
            coor_answers.append(answer[0])
            # case Question 1: A => Needs to compare the x0 of answer title 
            coor_answers_cover = compare_coors(coor_answers_cover, [arr_key_title[i][0], answer[0][1], answer[0][2], answer[0][3]])
        else:
            coor_answers.append(arr_key_title[i])
    
    # check if question overlaps next question
    if coor_answers_cover[3] > question[key][3]:
        coor_answers_cover[3] = question[key][3]
    
    return [coor_answers, coor_answers_cover]

def compare_coors(coor, coor_m):
    """Get the smallest x0, y0 and largest x1,y1 between two lists

    Args:
        coor (list): given list
        coor_m (list): given list

    Returns:
        list: list containing the smallest x0, y0 and largest x1,y1 between two lists
    """
    coor_new = copy.deepcopy(coor)
    # get smallest x0, y0
    coor_new[0] = min(coor[0], coor_m[0])
    coor_new[1] = min(coor[1], coor_m[1])
    # get largest x1, y1
    coor_new[2] = max(coor[2], coor_m[2])
    coor_new[3] = max(coor[3], coor_m[3])
    
    return coor_new

def check_column_answers_two_options(coor_answers):
    """Get column when there are two answer options

    Args:
        coor_answers (list): list of answer options' coordinates

    Returns:
        int: number of column
    """
    y_average_B = (coor_answers[1][1] + coor_answers[1][3])/2
    if y_average_B < coor_answers[0][3]:
        return 2
    return 1

def check_column_answers_three_options(coor_answers):
    """Get column when there are three answer options

    Args:
        coor_answers (list): list of answer options' coordinates

    Returns:
        int: number of column
    """
    y_average_B = (coor_answers[1][1] + coor_answers[1][3])/2
    if y_average_B < coor_answers[0][3]:
        return 4
    
    return 1 
    
def check_column_answers_four_options(coor_answers):
    """Get column when there are four answer options

    Args:
        coor_answers (list): list of answer options' coordinates

    Returns:
        int: number of column
    """
    y_average_D = (coor_answers[3][1] + coor_answers[3][3])/2
    if y_average_D < coor_answers[0][3]:
        return 4
    if y_average_D < coor_answers[2][3]:
        return 2
    
    return 1

def smooth_four_column_answers(coor, coor_cover, arr_key_title):
    """Adjust coordinates of answer options to cover the content of answer options

    Args:
        coor (list): list of answer option coordinates
        coor_cover (list): list of box covering answer options
        arr_key_title (list): list of answer options' titles' coordinates

    Returns:
        list: list containing the coordinates of answer options' content
    """
    coor_c = copy.deepcopy(arr_key_title)
    
    # set vertical starting point (y0) of four option to y0 of coor cover
    coor[0][1] = coor[1][1] = coor[2][1] = coor[3][1] = coor_cover[1]
    # set vertical ending point (y1) of four option to y1 of coor cover
    coor[0][3] = coor[1][3] = coor[2][3] = coor[3][3] = coor_cover[3]
    # set horizontal ending point (x1) of fourth option to x1 of coor cover
    coor[3][2] = coor_cover[2]
    
    # set horizontal ending point (x1) of current option to horizontal starting point (x0) of next question's title
    coor[0][2] = coor_c[1][0]
    coor[1][2] = coor_c[2][0]
    coor[2][2] = coor_c[3][0]
    
    return get_answer_content(coor, coor_c)


def smooth_two_column_answers(coor, coor_cover, arr_key_title, question, key):
    """Adjust coordinates of answer options to cover the content of answer options

    Args:
        coor (list): list of answer option coordinates
        coor_cover (list): list of box covering answer options
        arr_key_title (list): list of answer options' titles' coordinates

    Returns:
        list: list containing the coordinates of answer options' content
    """
    #check if question overlaps next question
    if coor_cover[1][3] > question[key][3] and coor_cover[1][1] < question[key][3] :
        coor_cover[1][3] = question[key][3]

    if coor_cover[0][3] > coor_cover[1][1]:
        coor_cover[0][3] = coor_cover[1][1] - 1
    
    # get the widest length of answers by comparing length of coor_cover and length of question
    # because some answers do not cover the full width
    if coor_cover[1][2] < question[key][2] or coor_cover[0][2] < question[key][2]:
        coor_cover[1][2] = question[key][2]
        coor_cover[0][2] = question[key][2]

    # set vertical starting point (y0) of options to y0 of cover
    coor[0][1] = coor[1][1] = coor_cover[0][1]
    coor[2][1] = coor[3][1] = coor_cover[1][1]
    
    # set vertical ending point (y1) of options to y1 of cover
    coor[0][3] = coor[1][3] = coor_cover[0][3]
    coor[2][3] = coor[3][3] = coor_cover[1][3]
    
    # set horizontal ending point (x1) of second and fourth option to max width
    coor[1][2] = coor[3][2] = coor_cover[0][2] if coor_cover[0][2] >= coor_cover[1][2] else coor_cover[1][2]
    
    # set horizontal ending point (x1) of current question to horizontal starting point (x0) of next question title
    coor[0][2] = arr_key_title[1][0]
    coor[2][2] = arr_key_title[3][0]
    
    coor = get_answer_content(coor, arr_key_title)
    
    return coor

def smooth_one_column_answers(coor, coor_cover, arr_key_title):
    """Adjust coordinates of answer options to cover the content of answer options

    Args:
        coor (list): list of answer option coordinates
        coor_cover (list): list of box covering answer options
        arr_key_title (list): list of answer options' titles' coordinates

    Returns:
        list: list containing the coordinates of answer options' content
    """
    # set vertical ending point (y1) of third option to vertical starting point (y0) of fourth option
    coor[2][3] = min(coor[2][3], coor[3][1])
    # set vertical ending point (y1) of second option to vertical starting point (y0) of third option
    coor[1][3] = min(coor[1][3], coor[2][1])
    # set vertical ending point (y1) of first option to vertical starting point (y0) of second option
    coor[0][3] = min(coor[0][3], coor[1][1])
    # set horizontal ending point (x1) of four options to x1 of coor over
    coor[0][2] = coor[1][2] = coor[2][2] = coor[3][2] = coor_cover[2]
    # check if question overlaps next question
    coor[3][3] = min(coor[3][3], coor_cover[3])
 
    return get_answer_content(coor, arr_key_title)

def smooth_two_column_answers_two_options(coor, coor_cover, arr_key_title):
    """Adjust coordinates of answer options to cover the content of answer options

    Args:
        coor (list): list of answer option coordinates
        coor_cover (list): list of box covering answer options
        arr_key_title (list): list of answer options' titles' coordinates

    Returns:
        list: list containing the coordinates of answer options' content
    """
    # set vertical starting point (y0) of both options to y0 of coor over 
    coor[0][1] = coor[1][1] = coor_cover[1]
    # set ending vertical point (y1) of both options to y1 of coor over 
    coor[0][3] = coor[1][3] = coor_cover[3]
    # set horizontal ending point (x1) of second options to x1 of coor over 
    coor[1][2] = coor_cover[2] 
    # set horizontal ending point (x1) of fist options to horizontal starting point (x0) of second option's title
    coor[0][2] = arr_key_title[1][0]
        
    return get_answer_content(coor, arr_key_title)


def smooth_one_column_answers_three_options(coor, coor_cover, arr_key_title):
    """Adjust coordinates of answer options to cover the content of answer options

    Args:
        coor (list): list of answer option coordinates
        coor_cover (list): list of box covering answer options
        arr_key_title (list): list of answer options' titles' coordinates

    Returns:
        list: list containing the coordinates of answer options' content
    """
    # set vertical ending point (y1) of current question to vertical starting point (y0) of next option 
    coor[1][3] = min(coor[2][1], coor[1][3])
    coor[0][3] = min(coor[1][1], coor[0][3])
    
    # set horizontal ending point (x1) of three options to x1 of coor over
    coor[0][2] = coor[1][2] = coor[2][2] = coor_cover[2]
    
    return get_answer_content(coor, arr_key_title)


def get_answer_content(coor, arr_key_title):
    """Set starting coordinates of answer options' content

    Args:
        coor (list): list of answer options' coordinates
        arr_key_title (list): list of answer options' titles' coordinates

    Returns:
        list: list containing answer options' content' coordinates
    """
    # set the starting x0 of option's content to the end of the option's title
    coor[0][0] = arr_key_title[0][2]
    if len(coor) > 1:
        coor[1][0] = arr_key_title[1][2]
    if len(coor) > 2:
        coor[2][0] = arr_key_title[2][2]
    if len(coor) > 3:
        coor[3][0] = arr_key_title[3][2]
    
    return coor

def get_json_page(page, type_flag, flag_first_page=False):
    """Get page's jason after deleting header and footer

    Args:
        page (fitz.page): information of page
        flag_first_page (bool, optional): check if page is first page. Defaults to False.

    Returns:
        list: list containing blocks
    """
    blocks = page.get_text("json")
    blocks_json = json.loads(blocks)
    block_main = get_block_main(blocks_json['blocks'], type_flag, flag_first_page)
    
    return block_main

def get_question_0(page):
    blocks = get_json_page(page, 0, True)
    answers_options = {}
    num_q = 1
    append_reading = False
    for block in blocks:
        if num_q > 2:
            break
        # -- check lines in block --
        if "lines" in block:
            for line in block['lines']:
                text_spans = get_text_spans(line)
                # -------- check title questions ------------------------
                if check_question_title(text_spans, line):
                    if append_reading:
                        num_q -= 1
                        append_reading = False
                    
                    if check_reading_passage(text_spans):
                        append_reading = True
                    
                    num_q += 1
                    
                # --------------------- OPTION ANSWERS ---------------------------------------
                answers_options = check_answer_option(page,
                    num_q, False, line, text_spans, answers_options)

    return answers_options

def check_question_contain_title_answer(answers_options, text_spans, line, num_q, page):
    """Check if questions contains answer title (for example: Question 4: A.)

    Args:
        answers_options (dict): coordinate of options of answers
        text_spans (str): content of current line
        line (dict): information of current line
        num_q (int): question's number
        page (fitz.Page): information of current page
    Returns:
        list: list containing answer options' coordinates and boolean value to start lookign for answer options
    """
    if re.search(r"^(\s+)?(Question)+\s+[0-9]+(\:|\.)?(\s+)?(A\.)(\s+)?", text_spans):
        bbox = page.search_for("A.", clip = fitz.Rect(line["bbox"][0],line["bbox"][1],line["bbox"][2],line["bbox"][3]))
        answers_options[f'question_{num_q}'] = [[
            [bbox[0].x0, bbox[0].y0, bbox[0].x1, bbox[0].y1, "A.", line['spans'][0]['ascender'], line['spans'][0]['color'], line['spans'][0]['flags']],
            [bbox[0].x1, line["bbox"][1], line["bbox"][2], line["bbox"][3]]
        ]]

    return answers_options

def check_mediabox_block(block):
    """Check if either block's x0 or block's y0 is negative

    Args:
        block (dict): information of block

    Returns:
        bool: Return true if block's x0 or block's y0 is negative
    """
    return block["bbox"][0] < 0 or block["bbox"][1] < 0
        
def check_mediabox_height(block, page_height):
    """Check if block's height exceed page's height

    Args:
        block (dict): information of block
        page_height (int): height of page

    Returns:
        bool: Return true if block's height exceed page's height
    """
    return block["bbox"][3] > page_height
        
def process_answer_titles_less_than_4(answers_option, ascender_descender_option):
    
    if ascender_descender_option[2] >= 16:  # flags
        index_negative = [i for i, item in enumerate(answers_option) if item[0][7] < 16]
    elif ascender_descender_option[1] > 0:  # color
        index_negative = [i for i, item in enumerate(answers_option) if item[0][6] == ascender_descender_option[1]]
    else: # ascender
        index_negative = [i for i, item in enumerate(answers_option) if item[0][5] == ascender_descender_option[0]]
    
    for i in sorted(index_negative, reverse=True):
        answers_option.pop(i)
    
    return answers_option

def process_answer_titles(answers_option, ascender_descender_option):
    """Test the eligibility of answers' options

    Args:
        answers_option (list): coo
        ascender_descender_option (list): list of font ascender, font descender, and font flag

    Returns:
        list: Answer's options after being processed
    """
    if ascender_descender_option[2] >= 16:  # flags
        index_negative = [i for i, item in enumerate(answers_option) if item[0][7] < 16]
    elif ascender_descender_option[1] > 0:  # color
        index_negative = [i for i, item in enumerate(answers_option) if item[0][6] != ascender_descender_option[1]]
    else: # ascender
        index_negative = [i for i, item in enumerate(answers_option) if item[0][5] != ascender_descender_option[0]]
    
    # if len(answers_option) - len(index_negative) == 4:
    index_first = 0
    for i in list(range(0, len(answers_option))):
        if i not in index_negative:
            index_first = i
            break
    
    for index in sorted(index_negative, reverse=True):
        # make sure merged content belongs to current question
        if index > index_first and answers_option[index - 1][1][3] < answers_option[index][1][1]:
            # merge content of removed index to answer option
            answers_option[index - 1][1] = compare_coors(answers_option[index - 1][1], answers_option[index][1])
        answers_option.pop(index)
    
    return answers_option

def check_answer_option(page, num_q, flag_explain_in_question, line, text_spans, answers_options):
    """ Check if answer's option starts at current line

    Args:
        page (fitz.Page): information of page
        num_q (int): question's number
        flag_explain_in_question (bool): check if there is explanation in question
        flag_answers_options (bool): check if line is searching for answer's options
        line (dict): information of line
        text_spans (str): content of line
        answers_options (dict): information of answers' options

    Returns:
        list: list containg information of answers' options and boolean value to check if line is searching for answer's options
    """
    if flag_explain_in_question == False:
        if re.search(r"(\.)?((\s+)?[A-D]{1}(\s+)?\.(\s+)?)|^(\.)?((\s+)?[A-D]{1}(\s+)?(\.)?(\s+)?)", text_spans):
            r2 = re.compile("(\.)?((\s+)?[A-D]{1}(\s+)?(\.)?(\s+)?)")
            data = r2.findall(text_spans)
            if len(data) <= 1 or len(line["spans"]) == 1:
                for item in line["spans"]:
                    if re.search("^(\.)?((\s+)?[A-D]{1}(\s+)?(\.)?(\s+)?)$|^((\s+)?[A-D]{1}(\s+)?\.(\s+)?)|^((\s+)?[A-D]{1}(\s)(\s+)?)", item['text']):
                        if len(data) == 4:
                            if re.search(r"^[A-D\s]*$", item["text"]): #text only contains A B C D
                                answers_options = get_answers_options_without_value(answers_options, item, flag_explain_in_question, num_q, line)
                            else:
                                answers_options = get_answers_options_multiple(len(data), page, item, answers_options, flag_explain_in_question, num_q, line, text_spans)
                                break

                        answers_options = add_option_answer(
                        item['bbox'] + [item['text'], item['ascender'], item['color'], item['flags']], answers_options, num_q)
                        answers_options = get_answers_options(flag_explain_in_question, answers_options, num_q, line)
                        break
            else:
                answers_options = get_title_answer_plural(
                    line, answers_options, num_q, text_spans, page)

    # add text to answer
    if f"question_{num_q - 1}" in answers_options and len(answers_options[f"question_{num_q - 1}"]) > 0:
         # only add when option does not have text and not add next title value (exp: B C D)
        if len(answers_options[f"question_{num_q - 1}"][-1][1]) < 5 and not re.search("^[A-D](\.){0,1}$", text_spans.replace(" ", "")):
            # find number of extra option. Exp: A B C => B C are the extra options
            r2 = re.compile("\s{1,}?((\s+)?[A-D]{1}(\s+)?(\.)?(\s+)?)")  
            data = r2.findall(text_spans)

            # find option 
            r3 = re.compile("(\.)?((\s+)?[A-D]{1}(\s+)?(\.)?(\s+)?)") 
            data_1 = r3.findall(text_spans)

            len_ans = len(answers_options[f"question_{num_q - 1}"])
            if len(data) < 1 or len(data_1) == 1: # text line does not contain extra options
                if len(answers_options[f"question_{num_q - 1}"][-1][1]) < 5: # only need to add text to option the first time
                    answers_options[f"question_{num_q - 1}"][-1][1].append(text_spans)
            else:
                # case: A. 12 B.4 => A needs to be marked as "Have Text"
                for i in range(len(data)):
                    if len_ans-2-i >= 0 and len(answers_options[f"question_{num_q - 1}"][len_ans-2-i][1]) < 5:
                        answers_options[f"question_{num_q - 1}"][len_ans-2-i][1].append("Have Text")
                answers_options[f"question_{num_q - 1}"][-1][1].append(text_spans)

    return answers_options

def check_answer_without_value(answer):
    """Chekc if answer option has content

    Args:
        answer (list): information about answer option

    Returns:
        boolean: return True if answer options do not context
    """
    count = 0
    r2 = re.compile("[A-D](\.)?(\s+)")

    for option in answer:        
        # check title contains multiple question titles: text A B C
        if len(answer) < 4 and len(option[1]) > 4 and len(r2.findall(option[0][4])) >= 2:
            return True

        if len(option[1]) <= 4: # answers without content
            count += 1

    return count >= 2


def get_answers_options_without_value(answers_options, item, flag_explain_in_question, num_q, line):
    """Process answer' option

    Args:
        answers_options (dict): information of answers' options
        item (fitz.span): current span 
        flag_explain_in_question (bool): check if there is explanation in question
        num_q (int): question's number
        line (dict): information of line

    Returns:
        _type_: _description_
    """
    answers_options = add_option_answer(
                [item["bbox"][0], item["bbox"][1], item["bbox"][2], item["bbox"][1]] + [item["text"], item['ascender'], item['color'], item['flags']], answers_options, num_q) 
    answers_options = get_answers_options(flag_explain_in_question, answers_options, num_q, line)
    
    return answers_options         

def get_answers_options_multiple(len_options, page, item, answers_options, flag_explain_in_question, num_q, line,text_spans):
    """Process answer' option when options are on the same span's text`

    Args:
        len_options (int): number of questions
        page (fitz.Page): information of page
        item (dict): information of span
        answers_options (dict): information of answers' options
        flag_answers_options (bool): check if line is searching for answer's options
        flag_explain_in_question (bool): check if there is explanation in question
        num_q (int): question's number
        line (dict): information of line

    Returns:
        dict: information of answers' options after being processed
    """
    options = ["A.", "B.", "C.", "D."]

    for i in range(len_options):
        bbox = page.search_for(options[i], clip = fitz.Rect(item["bbox"][0],item["bbox"][1],item["bbox"][2],item["bbox"][3]))
        if len(bbox) > 0:
            answers_options = add_option_answer(
                [bbox[0].x0, bbox[0].y0, bbox[0].x1, bbox[0].y1] + [options[i], item['ascender'], item['color'], item['flags']], answers_options, num_q)                
            answers_options = get_answers_options(flag_explain_in_question, answers_options, num_q, line)
    return answers_options 

def get_title_answer_plural(line, answers_options, num_q, text_spans, page):
    """Process answers' option when options are in multiple span

    Args:
        line (dict): information of line
        answers_options (dict): information of answers_options
        num_q (int): question's number
    Returns:
        dict: information of answers_options after being processed
    """      
    for item in line["spans"]:
        if re.search("^(\.)?((\s+)?[A-D]{1}(\s+)?(\.)?(\s+)?)$|^((\s+)?[A-D]{1}(\s+)?\.(\s+)?)", item['text']):
            # -- True: title standard --
            span = item['bbox'] + [item['text'],
                                   item['ascender'], item['color'], item['flags']]
            answers_options = add_option_answer(span, answers_options, num_q)
        else:
            answers_options = get_answers_options(
                False, answers_options, num_q, {'bbox': item['bbox']})
        
    return answers_options

def check_question_width(page, line, text_spans):
    """Get coordinator of question title when the text includes the the question title and content

    Args:
        page (fitz.Page, optional): information of page
        line (dict): information of line
        text_spans (string): content of line
    Returns:
        list: coordinates of title after being checked
    """
    bbox = search_text_coor(page, line["bbox"], text_spans)
    return [bbox[0].x0, bbox[0].y0, bbox[0].x1, bbox[0].y1]

def search_text_coor(page, coor, text_spans):
    """ Search the coordinator of text_spans among the given coor
    Args:
        page (fitz.Page, optional): information of page
        coor (list): coordinates that create a rectangle, which we find the question title inside 
        text_spans (string): content of line

    Returns:
        _type_: _description_
    """
    # find full first question title (exp: Question 1:)
    title_list = re.search(r"(Câu|Cau|Bài|Question)(\s+)?(\d+)(\s+)?(\:|\.)?", text_spans) 
    title = title_list.group(1) if title_list is not None else ""
    num_first = title_list.group(3) if title_list is not None else 1
    extra = title_list.group(5) if title_list.group(5) is not None else ""
    # the space between question title "Question" and question number"1". 
    # in some case, there can be multiple spaces between "Question" and "1" (exp: Question    1:)
    white_space_1 = title_list.group(2) if title_list.group(2) is not None else " "
    # the space between question number "1" and extra character like ":". 
    # in some case, there can be multiple spaces between "1" and ":" (exp: Question 1    :)
    white_space_2 = title_list.group(4) if title_list.group(4) is not None else ""
    full_title = title + white_space_1 + str(num_first) + white_space_2 + extra 
    bbox = page.search_for(full_title, clip = fitz.Rect(coor[0], coor[1], coor[2], coor[3]))
    
    return bbox

def get_title_question(line, page):
    """Return the coordinates of question's title

    Args:
        line (dict): information of line
        page (fitz.Page, optional): information of page.
    Returns:
        list: list containing question's coordinates
    """
    text_spans = ''
    coor = []
    for item in line["spans"]:
        text_spans += item['text']
        if len(coor) == 0:
            coor = item['bbox']
        else:
            coor = compare_coors(coor, item['bbox'])
        if re.search(r"^(\s+)?(Câu|Cau|Bài|Question)+(\s|s\+)+[0-9]+(\:|\.)?(\s+)?$", text_spans):
            # -- True: title standard --
            coor += [text_spans]
            break
        elif re.search(r"^(\s+)?(Câu|Cau|Bài|Question)+(\s|s\+)+[0-9]+(.*)?(\:|\.)?(\s+)?", text_spans):
            coor = check_question_width(page, line, text_spans)
            coor += [text_spans]
            break
        elif re.search(r"^[0-9]+(\:|\.)?\s", text_spans.strip()):
            coor = check_question_width(page, line, text_spans)
            coor += [text_spans]
    
    return coor

def add_option_answer(span, answers_options, num_q):
    """Add option coordinates to list answers_options

    Args:
        span (list): list of span's coordinates
        answers_options (dict): information of answers
        num_q (int): question's number
    Returns:
        dict: dictionary of answers after adding the option
    """
    # -- add option answers --
    data_op = [span, [span[0], span[1], span[2], span[3]]]
    if f'question_{num_q - 1}' in answers_options:
        answers_options[f'question_{num_q - 1}'].append(data_op)
    else:
        answers_options[f'question_{num_q - 1}'] = [data_op]

    return answers_options

def get_answers_options(flag_explain_in_question, answers_options, num_q, line):
    """Add coordinates of answer's value

    Args:
        flag_answers_options (bool): check if line is searching for answer's options
        flag_explain_in_question (bool): check if there is explanation in question
        answers_options (dict):information of answers
        num_q (int): question's number
        line (dict): information of line

    Returns:
        dict: information of answers' options
    """
    
    if f'question_{num_q - 1}' in answers_options and flag_explain_in_question == False:
        if line['bbox'][3] > answers_options[f'question_{num_q - 1}'][-1][0][1]:
            if len(answers_options[f'question_{num_q - 1}'][-1]) == 2:
                answers_options[f'question_{num_q - 1}'][-1][1] = compare_coors(
                    answers_options[f'question_{num_q - 1}'][-1][1], line['bbox'])
            else:
                answers_options[f'question_{num_q - 1}'][-1].append(
                    line['bbox'])
    
    return answers_options

def remove_item_in_blocks(blocks, block, line, keep_line = False):
    """Remove previous blocks starting from given block

    Args:
        blocks (list): list of page's blocks
        block (list): information of block
        line (dict): information of line

    Returns:
        list: list of blocks after removing previous blocks starting from given block
    """
    # -- delete previous block --
    index = blocks.index(block)
    del blocks[:index]
    # -- delete line used --
    if keep_line == False:
        index = blocks[0]['lines'].index(line)
        del blocks[0]['lines'][:index+1]
        if len(blocks[0]['lines']) == 0 or get_text_lines(blocks[0]) == "":
            del blocks[0]
    
    return blocks

def process_correct_answer(blocks):
    """Process correct answers

    Args:
        blocks (list): list of page's blocks

    Returns:
        list: list containing returning type, correct answers and question's number
    """
    text_spans = get_text_lines(blocks[0])
    if check_correct_answer_text(text_spans):
        del blocks[0]

    # -- check format user for the correct answers --
    for block in blocks:
        # -- check lines in block --
        if "lines" in block:
            text_spans = get_text_lines(block)

            if check_exam_multiple(text_spans):
                return [{}, {}, {}, {}]
            
            if text_spans == "":
                continue
            
            # test has no correct answer and only explain
            if check_explain_text(text_spans):
                return process_explain(blocks, 1)
                
            if len(block['lines']) == 1:
                break
            
            # test has correct answer
            text_span_1 = block['lines'][0]['spans'][0]['text'].strip()
            text_span_2 = block['lines'][1]['spans'][0]['text'].strip()
            if check_correct_answer_type_1(text_span_1):
                return get_correct_answer_type_1(blocks)
            elif re.search(r"^[A-F]{1}$", text_span_2):
                return get_correct_answer_type_2(blocks)
            elif re.search(r"^[0-9]$", text_span_1) or re.search(r"^[0-9]$", text_span_2):
                return get_correct_answer_type(blocks)
            break
        else:
            index = blocks.index(block)
            del blocks[index]
    
    return [{}, {}, {}, {}, -1, 99]

def check_correct_answer_type_1(text_span):
    """Check if the given text has number and letter in one span's text

    Args:
        text_span (str): given text 

    Returns:
        bool: Return true if the given text has number and letter in one span's text
    """
    if re.search(r"^[0-9]+(\s+)?(\-|\.)(\s+)?[A-F]{1}$", text_span):
        return True
    return False
    
def check_answer_option_title(text_span):
    """Check if given text is the start of answer option 

    Args:
        text_span (str): given text 

    Returns:
        bool: Return true if given text is the start of answer option 
    """
    if re.search(r"^[A-F]{1}$", text_span):
        return True
    return False

def check_exam_multiple(text_spans):
    """Check if there are multiple exams in one pdf

    Args:
        text_spans (str): content of line

    Returns:
        bool: Return true if given text contains "Mã đề"
    """
    if re.search(r"^Mã đề|Đề", text_spans.strip()):
        return True
    return False

def check_correct_answer_text(text_spans):
    """Check if given text contains start of correct answers 

    Args:
        text_spans (str): content of line

    Returns:
        bool: Return true if given text contains start of correct answers
    """
    if re.search(r"^(Đáp án|ĐÁP ÁN|BẢNG ĐÁP ÁN|HƯỚNG DẪN GIẢI – ĐÁP ÁN)", text_spans.strip()):
        return True
    return False

def check_explain_text(text_spans):
    """Check if given text contains explanation 

    Args:
        text_spans (str): content of line

    Returns:
        bool: Return true if given text contains explanation
    """
    if re.search(r"^HƯỚNG DẪN GIẢI|HƯỚNG DẪN GIẢI|Hướng dẫn giải|Lời giải", text_spans.strip()):
        return True
    return False
    
def check_essay_text(text_spans):
    """Check if given text contains essays 

    Args:
        text_spans (str): content of line

    Returns:
        bool: Return true if given text contains essays
    """
    # text does not include trac nghiem part 
    if re.search(r"^(?!.*(trac nghiem|trắc nghiệm)).*", text_spans.strip()) and re.search(r"^(([A-F]{1})?(\s+)?(\:|\.)?(\s+)?(Phần|PHẦN|[A-F]{1}|PHẦN CÂU HỎI)?(\s+)?(I|II|III)?(\s+)?(\:|\.|\–|\-|\—)??(\s+)?(\.*?)?)?(\s+)?(Tự luận|TỰ LUẬN)|tự luận|PHẦN TỰ LUẬN", text_spans.strip()):
        return True
    return False

def check_end_text(text_spans):
    """Check if given text contains the end of document 

    Args:
        text_spans (str): content of line

    Returns:
        bool: Return true if given text contains the end of document 
    """
    if re.search(r"^((((–|—|-|_|\…|\.)(\s+)?)+)?(\s)?(HẾT|Hết|Het|HET|THE END))", text_spans.strip()):   
        return True
    return False

def check_reading_passage(text_spans):
    """Check if given text contains beginning of English vocabularies 

    Args:
        text_spans (str): content of line

    Returns:
        bool: Return true if given text contains beginning of English vocabularies 
    """
    if re.search(r"^Mark the|^Read the|Đọc văn bản", text_spans.strip()):
        return True
    return False

def check_question_title(text_spans, line):
    """Check if given text contains beginning of question title

    Args:
        text_spans (str): content of line

    Returns:
        bool: Return true if given text contains question title
    """
    if re.search(r"^(\s+)?(Câu|Cau|Bài|Question)+(\s)+[0-9]+(.*)?(\:|\.)?(\s+)?|^Mark the|^Read the|Đọc văn bản", text_spans.strip()) or re.search(r"^[0-9]+(\:|\.)\s", text_spans.strip()) and line["spans"][0]["flags"] >= 16:
        return True
    return False

def process_explain_in_correct_answer(blocks, correct_answers):
    """Process explains when there are explanation and correct answers 

    Args:
        blocks (list): list of page's blocks

    Returns:
        list: list containing return type, coordinates of explains and number of questions
    """
    data = process_explain(blocks, 1)
    data[3] = correct_answers
    
    return data

# -- case correct answer format: 1.C
def get_correct_answer_type_1(blocks):
    """Process correct answers when one span includes both number and letter of correct answers

    Args:
        blocks (list): list of page's blocks
    Returns:
        list: list of return type, correct answers and question number
    """
    correct_answers = {}
    for block in blocks:
        # -- check lines in block --
        if "lines" in block:
            for line in block['lines']:
                text_spans = get_text_spans(line).strip()
                if check_correct_answer_type_1(text_spans):
                    arr_correct = re.split(r"[-.]", text_spans)
                    if len(arr_correct) > 1:
                        correct_answers[f'question_{arr_correct[0]}'] = arr_correct[1]
                elif check_explain_text(text_spans):
                    return process_explain_in_correct_answer(remove_item_in_blocks(blocks, block, line, True), correct_answers)
                elif check_question_title(text_spans, line):
                    return process_explain_in_correct_answer(remove_item_in_blocks(blocks, block, line, True), correct_answers)
    
    return [{}, {}, {}, correct_answers, -1, 99]

# -- case correct answer format: span 1: "1" and span 2: "C"
def get_correct_answer_type_2(blocks):
    """Process correct answers when one span includes the number and the next span includes the letter

    Args:
        blocks (list): list of page's blocks
    Returns:
        list: list of return type, correct answers and question number
    """
    correct_answers = {}
    num_correct = 1
    for block in blocks:
        # -- check lines in block --
        if "lines" in block:
            # for i in range(0, len_line):
            for line in block['lines']:
                for span in line['spans']:
                    text_span = re.sub(r"\s+|\.|\-", "", span['text'])
                    if text_span.isnumeric():
                        correct_answers[f'question_{text_span}'] = text_span
                        num_correct = text_span
                    elif check_answer_option_title(text_span):
                        correct_answers[f'question_{num_correct}'] = text_span
                    elif check_explain_text(text_span):
                        return process_explain_in_correct_answer(remove_item_in_blocks(blocks, block, line), correct_answers)
                    elif check_question_title(text_span, line) or check_question_title(text_span, line):
                        return process_explain_in_correct_answer(remove_item_in_blocks(blocks, block, line, True), correct_answers)
    
    return [{}, {}, {}, correct_answers, -1, 99]

def get_correct_answer_type(blocks):
    """Check what type of correct answers is

    Args:
        blocks (list): list of page's blocks

    Returns:
        list: list containing returning type, correct answers and question's number
    """
    correct_answers = {}
    num_title = 1
    
    for block in blocks:
        # -- check lines in block --
        if "lines" in block:
            for line in block['lines']:
                for span in line['spans']:
                    text_span = span['text'].strip()
                    if re.search(r"^[A-F]{1}$", text_span):
                        correct_answers[f'question_{num_title}'] = text_span
                        num_title +=1
                    elif check_explain_text(text_span):
                        return process_explain_in_correct_answer(remove_item_in_blocks(blocks, block, line), correct_answers)
                    elif check_question_title(text_span, line):
                        return process_explain_in_correct_answer(blocks, correct_answers)
                          
    return [{}, {}, {}, correct_answers, -1, 99]

def process_explain(blocks, num_q):
    """Process explanation

    Args:
        blocks (list): list of page's blocks
        num_q (int): question's number

    Returns:
        list: list containing returning type, explanation and question's number
    """
    explains = {}
    for block in blocks:
        # -- check lines in block --
        if "lines" in block:
            text_spans = ''
            for line in block['lines']:
                text_spans = get_text_spans(line)
                
                if check_explain_text(text_spans):
                    continue
                
                if check_question_title(text_spans, line):
                    # -- The case explain question number is not order
                    # -- get first question number
                    g_num_q = re.search(r'\d+', text_spans)
                    if g_num_q:
                        num_q = int(g_num_q.group())
                    explains[f'question_{num_q}'] = line['bbox'] + \
                        [text_spans]
                    num_q += 1
                    continue
                
                explains = merge_question(
                    line, explains, num_q, text_spans)
        else:
            explains = process_line_image(
                explains, num_q, block)
    
    return [{},{}, explains, {}, num_q, 4]

def process_line_image(questions, num_q, block):
    """Process image

    Args:
        questions (dict): information of questions's coordinates and questions title's coordinates
        num_q (int): question's number
        block (list): information of block

    Returns:
        questions: update question' coordinate after processing image
    """
    if f'question_{num_q - 1}' not in questions:
        questions[f'question_{num_q - 1}'] = block['bbox'] + [""]
    elif f'question_{num_q - 1}' in questions and block['bbox'][3] >= questions[f'question_{num_q - 1}'][3]:
        questions[f'question_{num_q - 1}'] = compare_coors_with_text(
            questions[f'question_{num_q - 1}'], block['bbox'] + ['image'])
    else:
        questions = compare_image_outside(questions, block, block['image'])
    
    return questions

def process_stop_questions(blocks):
    """Process data when the end of document is found

    Args:
        blocks (list): list of page's blocks
        questions (dict): information of questions's coordinates and questions title's coordinates

    Returns:
        list: list containing returning type, questions and question's number 
    """
    text_spans = get_text_lines(blocks[0])
    if check_end_text(text_spans):
        del blocks[0]
    for block in blocks:
        # -- check lines in block --
        if "lines" in block:
            for line in block['lines']:
                text_spans = ''
                text_spans = get_text_spans(line)
                if check_correct_answer_text(text_spans.strip()):
                    data_answer = process_correct_answer(
                        remove_item_in_blocks(blocks, block, line))
                    return data_answer
                elif check_explain_text(text_spans):
                    return process_explain(remove_item_in_blocks(blocks, block, line), 1)
                else:
                    if len(block['lines']) == 1:
                        continue
                    text_span_1 = block['lines'][0]['spans'][0]['text'].strip()
                    text_span_2 = block['lines'][1]['spans'][0]['text'].strip()
                    if re.search(r"^[0-9]+(\s+)?(\:|\.)(\s+)?[A-F]{1}$", text_span_1):
                        return get_correct_answer_type_1(blocks)
                    elif re.search(r"^[A-F]{1}$", text_span_2):
                        return get_correct_answer_type_2(blocks)
                    elif re.search(r"^[A-F]{1}$", text_span_1) or re.search(r"^[A-F]{1}$", text_span_2):
                        return get_correct_answer_type(blocks)
    
    return [{}, {}, {}, {}, 1, 99]

def process_line_image_with_answer_in_questions(num_q, block, object_1, object_2):
    """Find what question the image belongs to

    Args:
        num_q (int): question's number
        block (dict): information of block
        object_1 (dict): information of questions or explanation
        object_2 (dict): information of explanation or questions

    Returns:
        list: list containing new coordinates of questions and explanation after finding what question the image belongs to
    """
    if f'question_{num_q - 1}' in object_1 and block['bbox'][3] >= object_1[f'question_{num_q - 1}'][3]:
        object_1[f'question_{num_q - 1}'] = compare_coors_with_text(
            object_1[f'question_{num_q - 1}'], block['bbox'] + ['image'])
    else:
        return compare_image_outside_two_object(object_1, object_2, block, 'image')
    return [object_1, object_2]

def compare_image_outside_two_object(object_1, object_2, line, text_spans):
    """Find what question the image belongs to when image belongs between two questions

    Args:
        object_1 (dict): information of questions or explanation
        object_2 (dict): information of explanation or questions
        line (dict): information of line
        text_spans (str): content of line

    Returns:
        list: list containing update coordinates of questions and explanation
    """
    key_1 = get_object_match_image(object_1, line)
    key_2 = get_object_match_image(object_2, line)
    if key_1 != "" and key_2 != "":
        if object_1[key_1][3] < object_2[key_2][3]:
            object_1[key_1] = compare_coors_with_text(
                object_1[key_1], line['bbox'] + [text_spans])
        else:
            object_2[key_2] = compare_coors_with_text(
                object_2[key_2], line['bbox'] + [text_spans])
    elif key_1 != "":
        object_1[key_1] = compare_coors_with_text(
            object_1[key_1], line['bbox'] + [text_spans])
    elif key_2 != "":
        object_2[key_2] = compare_coors_with_text(
            object_2[key_2], line['bbox'] + [text_spans])

    return [object_1, object_2]

def get_object_match_image(obj, line):
    """Return which question the line belongs to

    Args:
        obj (list): information of questions/explanations
        line (dict): information of line
    Returns:
        int: question's number
    """
    key_first = list(obj.keys())[0]
    for key in obj:
        # if the line is inside the the current key 
        # or the current key is the first question and position of line is covered by the end of key
        if obj[key][1] < (line['bbox'][3] + line['bbox'][1])/2 < obj[key][3] or (key_first == key and (line['bbox'][3] + line['bbox'][1])/2 < obj[key][3]):
            return key

    return ""


def compare_image_outside(questions, line, text_spans):
    """Check if the image belongs to previous question

    Args:
        questions (dict): information of questions's coordinates and questions title's coordinates
        line (dict): information of line
        text_spans (str): content of line

    Returns:
        dict: Updated questions's coordinaet to cover image
    """
    key_first = list(questions.keys())[0]

    for key in questions:
        if questions[key][1] < (line['bbox'][3] + line['bbox'][1])/2 < questions[key][3] or (key_first == key and (line['bbox'][3] + line['bbox'][1])/2 < questions[key][3]):
            questions[key] = compare_coors_with_text(
                questions[key], line['bbox'] + [text_spans])
            break

    return questions

def merge_question(line, questions, num_q, text_spans, answers_options = {}):
    """Update question's coordinates to cover the coordinates of answer options

    Args:
        line (dict): information of line
        questions (dict): information of questions's coordinates and questions title's coordinates
        num_q (int): question's number
        text_spans (str): content of line
        answers_options (dict):information of answers

    Returns:
        dict: Updated question's coordinates to cover the coordinates of answer options
    """
    if text_spans.strip() == "" and line["bbox"][2] - line["bbox"][0] < 4 or text_spans.isspace():
        return questions
    
    if len(answers_options) > 0 and f'question_{num_q - 1}' in answers_options:
        # make sure  line within question 
        # if could not find num_q, answer options are in two pages
        if f'question_{num_q - 1}' not in questions or line['bbox'][1] > questions[f'question_{num_q - 1}'][1]:
            # make sure line within answer option
            if line['bbox'][0] > answers_options[f'question_{num_q - 1}'][-1][1][2] or answers_options[f'question_{num_q - 1}'][-1][1][1] < line['bbox'][3]:
                # add coordinate of line to answers_options
                answers_options[f'question_{num_q - 1}'][-1][1] = compare_coors(
                answers_options[f'question_{num_q - 1}'][-1][1], line['bbox'])

    if f'question_{num_q - 1}' not in questions:
        questions[f'question_{num_q - 1}'] = line['bbox'] + [text_spans]
    else:
        if line['bbox'][3] > questions[f'question_{num_q - 1}'][1]:
            questions[f'question_{num_q - 1}'] = compare_coors_with_text(
                questions[f'question_{num_q - 1}'], line['bbox'] + [text_spans]) 
        elif text_spans.strip() != "":
            # the current text does not belong to current question
            # have to find which question the text belongs to
            questions = compare_question_outside(
                questions, line, text_spans, answers_options)

    return questions

def compare_question_outside(questions, line, text_spans, answers_options = {}):
    """Update question's coordinates to cover the coordinates of answer options when answer options belongs to the previous question

    Args:
        line (dict): information of line
        questions (dict): information of questions's coordinates and questions title's coordinates
        num_q (int): question's number
        text_spans (str): content of line
        answers_options (dict):information of answers

    Returns:
        dict: Updated question's coordinates to cover the coordinates of answer options
    """    
    for key in questions:
        # find what question the text belongs to 
        if questions[key][1] < (line['bbox'][1] + line['bbox'][3])/2 < questions[key][3]:
            questions[key] = compare_coors_with_text(questions[key], line['bbox'] + [text_spans])
            # -- case the text in answers options --
            if len(answers_options) > 0 and key in answers_options and len(answers_options[key]) > 0 and (answers_options[key][0][0][1] < line['bbox'][1] or answers_options[key][0][0][1] < line['bbox'][3]):
                len_answer = len(answers_options[key])
                arr_i = []
                for i in range(1, len_answer):
                    if answers_options[key][i][0][1] < (line['bbox'][1] + line['bbox'][3])/2 < answers_options[key][i][0][3]:
                        arr_i.append(i)
                for i in arr_i:
                    if answers_options[key][i][0][2] < line['bbox'][2]:
                        if len(answers_options[key][i]) == 2:
                            answers_options[key][i][1] = compare_coors(
                                answers_options[key][i][1], line['bbox'])
                        else:
                            answers_options[key][i].append(line['bbox'])
            break
    
    return questions

def compare_coors_with_text(coor, coor_m):
    """Get the smallest x0, y0 and largest x1,y1 between two lists

    Args:
        coor (list): given list
        coor_m (list): given list

    Returns:
        list: list containing the smallest x0, y0 and largest x1,y1 between two lists
    """
    coor_new = copy.deepcopy(coor)
    # get smallest x0, y0
    coor_new[0] = min(coor[0], coor_m[0])
    coor_new[1] = min(coor[1], coor_m[1])
    # get largest x1, y1 
    coor_new[2] = max(coor[2], coor_m[2])
    coor_new[3] = max(coor[3], coor_m[3])
    #append text
    coor_new[4] = coor[4] + coor_m[4]
    
    return coor_new

def get_block_main(blocks, type_flag, flag_first_page):
    """Delete header and footer

    Args:
        blocks (list):list of blocks
        flag_first_page (bool): check if page is first page

    Returns:
        list: list containing blocks
    """
    if len(blocks) < 3:
        return []
    if get_text_in_block(blocks[0], type_flag, True) == True:
        del blocks[0]
    elif get_text_in_block(blocks[1], type_flag) == True:
        del blocks[0:2]
    elif get_text_in_block(blocks[2], type_flag) == True:
        del blocks[0:3]
    elif get_text_in_block(blocks[len(blocks) - 1], type_flag, True):
        del blocks[-1:]
    if get_text_lines(blocks[0]).strip() == "" or (flag_first_page == True and blocks[0]['type'] == 1):
        del blocks[0]
    
    return blocks

def write_file(data, jsonName="data.json"):
    if os.path.exists(jsonName):
        os.remove(jsonName)

    with open(jsonName, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def process_explain_base64(explains, coor_x, doc, path_root_output = ""):
    """Create image of explanation

    Args:
        explains (list): list of explanation's coordinates
        coor_x (list): list of explanation's max width
        path_root_output (str): link to the output's file
    """
    coor_explains_result = defaultdict(list)
    for explain in explains:
        for key in explain[1]:
            coor_x[0] = min(explain[1][f"{key}"][0], coor_x[0])
            coor = [coor_x[0], explain[1][f"{key}"][1], explain[1][f"{key}"][2], explain[1][f"{key}"][3]]
            if key not in coor_explains_result:
                coor_explains_result[key] = [get_base64_title(doc[explain[0]], coor)]
            else:
                coor_explains_result[key].append(get_base64_title(doc[explain[0]], coor))
    return coor_explains_result
