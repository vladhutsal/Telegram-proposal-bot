#!/usr/bin/env python3

import telegram
import logging
import tempfile
from telegram_bot.credentials import TOKEN

from telegram_bot.Proposal import Proposal
from telegram_bot.ProposalDBHandler import ProposalDBHandler

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS    # import CSS
from docx import Document
from telegram import (
    InlineKeyboardMarkup,
    InlineKeyboardButton)

from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
    CallbackQueryHandler)


logging.getLogger('apscheduler.scheduler').propagate = False

# add description:
STORE_DATA, SELECT_ACTION, STORE_DOCX, STORE_ENGINEER_TO_DB = map(chr, range(4))

ADD_DOCX, ADD_INFO, ADD_NEW_ENGINEER, ADD_ENGINEERS_RATE,  = map(chr, range(5, 9))

EDIT_TITLE, CHOOSE_ENGINEER, CREATE_PDF, TEST = map(chr, range(10, 14))

SHOW_BUTTONS, CHOOSE_TITLE_TO_EDIT, ADD_ENGINEER_TO_PROPOSAL = map(chr, range(15, 18))


def start(update, context):
    db_handler = ProposalDBHandler()
    proposal = Proposal(db_handler)

    context.user_data['db_handler'] = db_handler
    context.user_data['proposal'] = proposal

    context.user_data['templates'] = {
        ADD_DOCX:                proposal.content_dict,
        ADD_INFO:                proposal.info_dict,
        ADD_NEW_ENGINEER:        proposal.engineer_dict,
        ADD_ENGINEERS_RATE:       db_handler.engineers_rates
    }

    # reset content dict when restarting proposal
    context.user_data['chat_id'] = update.message.chat_id
    context.user_data['test'] = False

    buttons = [[
        InlineKeyboardButton(text='Create new proposal',
                             callback_data=ADD_DOCX),
        InlineKeyboardButton(text='Test',
                             callback_data=str(TEST))
    ]]

    keyboard = InlineKeyboardMarkup(buttons)
    update.message.reply_text('Hi, I`ll help you to complete the proposal.')
    update.message.reply_text(text='What do you want to do?',
                              reply_markup=keyboard)

    return SELECT_ACTION


def show_buttons(update, context):
    proposal = context.user_data['proposal']

    buttons = []
    if proposal.finish:
        text = 'Create PFD'
        callback_data = CREATE_PDF
    else:
        text = 'Choose engineer'
        callback_data = CHOOSE_ENGINEER

    btn1 = add_button('Edit info', CHOOSE_TITLE_TO_EDIT)
    btn2 = add_button(text, callback_data)
    buttons = append_btns(buttons, btn1, btn2)

    text = '<b>What`s next?</b>'
    if getattr(update, 'callback_query'):
        update.callback_query.answer()
        keyboard = InlineKeyboardMarkup.from_row(buttons)
        update.callback_query.edit_message_text(text=text,
                                                reply_markup=keyboard,
                                                parse_mode=telegram.ParseMode.HTML)
    else:
        keyboard = InlineKeyboardMarkup.from_row(buttons)
        context.bot.send_message(chat_id=context.user_data['chat_id'],
                                 text=text,
                                 reply_markup=keyboard,
                                 parse_mode=telegram.ParseMode.HTML)
    return SELECT_ACTION


def init_template(update, context):
    query = update.callback_query
    proposal = context.user_data['proposal']
    proposal.current_dict = detach_id_from_callback(query.data)

    return next_title(update, context)


def init_add_info(update, context):
    templates = context.user_data['templates']
    proposal = context.user_data['proposal']

    proposal.current_dict = templates[ADD_INFO]
    proposal.reset_iter()

    return next_title(update, context)


def init_add_docx(update, context):
    templates = context.user_data['templates']
    proposal = context.user_data['proposal']

    proposal.current_dict = templates[ADD_DOCX]
    proposal.reset_iter()

    return ask_for_docx(update, context)


def init_add_engineers_rate(update, context):
    templates = context.user_data['templates']
    proposal = context.user_data['proposal']

    proposal.current_dict = templates[ADD_ENGINEERS_RATE]
    proposal.reset_iter()

    return next_title(update, context)


def init_add_new_engineer(update, context):
    templates = context.user_data['templates']
    proposal = context.user_data['proposal']

    update.callback_query.answer()
    proposal.current_dict = templates[ADD_NEW_ENGINEER]
    proposal.reset_iter()

    return next_title(update, context)


def ask_for_docx(update, context):
    query = update.callback_query
    context.bot.send_message(chat_id=context.user_data['chat_id'],
                             text='Send me your DOCX file with main content')
    query.answer(text='Waiting for your docx')
    return STORE_DOCX


# ================ FILL TEMPLATES WITH DATA
def next_title(update, context):
    proposal = context.user_data['proposal']

    try:
        proposal.get_next_title_id()
        return show_title(update, context)

    except StopIteration:
        return show_buttons(update, context)


def show_title(update, context):
    proposal = context.user_data['proposal']

    title_id = proposal.current_title_id
    title_name = proposal.get_bold_title(title_id)
    context.bot.send_message(chat_id=context.user_data['chat_id'],
                             text=title_name,
                             parse_mode=telegram.ParseMode.HTML)
    if title_id == 'PHT':
        return STORE_ENGINEER_TO_DB

    return STORE_DATA


def edit_title(update, context):
    proposal = context.user_data['proposal']

    query = update.callback_query
    proposal.current_title_id = detach_id_from_callback(query.data)
    proposal.edit_all = False
    query.answer()

    return show_title(update, context)


def store_data(update, context):
    proposal = context.user_data['proposal']

    user_content = update.message.text
    proposal.store_content(user_content)

    if proposal.edit_all:
        return next_title(update, context)

    elif not proposal.edit_all:
        proposal.edit_all = True

        return overview(update, context)


def store_engineer_to_db(update, context):
    proposal = context.user_data['proposal']
    db_handler = context.user_data['db_handler']

    photo_info = update.message.photo[-1]
    file_id = photo_info.file_id
    File_obj = context.bot.get_file(file_id=file_id)

    dir_path = 'engineers_photo'
    name = proposal.get_random_name()
    downloaded_photo_path = f'media/{dir_path}/{name}.jpg'
    path_for_template = f'../{dir_path}/{name}.jpg'
    File_obj.download(custom_path=downloaded_photo_path)
    proposal.store_content(path_for_template)
    proposal.finish = False

    # telegram_bot.py is no need to know about db_handler class
    err = db_handler.store_new_engineer_to_db(proposal.current_dict)
    proposal.reset_engineer_dict()
    if err:
        show_error_message(update, context)

    return show_buttons(update, context)


def store_docx(update, context):
    proposal = context.user_data['proposal']

    file_id = update.message.document.file_id
    name = proposal.get_random_name()
    docx_path = f'media/users_docx/{name}.docx'

    Docx_obj = context.bot.get_file(file_id=file_id)
    Docx_obj.download(custom_path=docx_path)
    proposal.content_dict = docx_parser(proposal, docx_path)

    return init_add_info(update, context)


def docx_parser(proposal, docx_path):
    doc = Document(docx_path)

    for content in doc.paragraphs:
        if content.style.name == 'Heading 2':
            try:
                proposal.get_next_title_id()
            except StopIteration:
                return True
        elif not content.text:
            pass
        else:
            proposal.store_content(content.text)
    return proposal.current_dict


# ================ EDIT AND OVERVIEW
# there will be two buttons - "Edit" and "Add info"/"Choose engineers"
def overview(update, context):
    proposal = context.user_data['proposal']

    context.bot.send_message(chat_id=context.user_data['chat_id'],
                             text='<b>Info you`ve provided:</b>',
                             parse_mode=telegram.ParseMode.HTML)
    for title_id in proposal.current_dict.keys():
        title = proposal.get_bold_title(title_id)
        content = proposal.get_title_content(title_id)
        context.bot.send_message(chat_id=context.user_data['chat_id'],
                                 text=f'{title}\n{content}',
                                 parse_mode=telegram.ParseMode.HTML)

    return show_buttons(update, context)


def choose_title_to_edit(update, context):
    proposal = context.user_data['proposal']

    query = update.callback_query
    current_dict = proposal.current_dict

    buttons = []
    for title_id in proposal.current_dict.keys():
        text = f'{current_dict[title_id][0]}'
        callback_data = f'{title_id}, {EDIT_TITLE}'
        btn = [add_button(text, callback_data)]
        append_btns(buttons, btn)

    append_btns(buttons, [add_button('<< Go back', SHOW_BUTTONS)])

    context.user_data['update_id'] = query.id
    query.answer()
    keyboard = InlineKeyboardMarkup(buttons)
    query.edit_message_text(text='Choose a title you want to edit:',
                            reply_markup=keyboard)

    return SELECT_ACTION


# ================ ENGINEERS
def choose_engineers(update, context):
    db_handler = context.user_data['db_handler']

    query = update.callback_query
    engineers = db_handler.get_engineers_id_list()
    engn_in_proposal = db_handler.engineers_in_proposal_id

    buttons = []
    if engineers:
        for engineer_id in engineers:
            engineer_name = db_handler.get_field_info(engineer_id, 'N')
            if engineer_id not in engn_in_proposal:
                callback_data = f'{engineer_id}, {ADD_ENGINEER_TO_PROPOSAL}'
                btn = [add_button(engineer_name, callback_data)]
                buttons.append(btn)

    if engn_in_proposal:
        callback_data = ADD_ENGINEERS_RATE
    else:
        callback_data = CREATE_PDF
    help_btns = [add_button('Add new engineer', ADD_NEW_ENGINEER),
                 add_button('Continue', callback_data)]
    buttons.append(help_btns)

    text = 'Choose engineers: '
    keyboard = InlineKeyboardMarkup(buttons)

    if query:
        query.answer()
        query.edit_message_text(text=text,
                                reply_markup=keyboard)
    else:
        context.bot.send_message(chat_id=context.user_data['chat_id'],
                                 text=text,
                                 reply_markup=keyboard)

    return SELECT_ACTION


def add_engineer_to_proposal(update, context):
    db_handler = context.user_data['db_handler']
    proposal = context.user_data['proposal']

    # add engineers id to list of engineers in current proposal:
    query = update.callback_query
    engineer_id = detach_id_from_callback(query.data)
    curr_list = db_handler.engineers_in_proposal_id
    curr_list.append(int(engineer_id))

    # add engineers id to dictionary as key {'engn_id': ['name', 'rate']}
    engineer_name = db_handler.get_field_info(engineer_id, 'N')
    db_handler.engineers_rates[engineer_id] = [f'Current rate for {engineer_name}', '']
    proposal.finish = True
    query.answer('Engineer added')

    return choose_engineers(update, context)


# ================ HELPERS
def append_btns(buttons, *args):
    for btn in args:
        buttons.append(btn)
    return buttons


def add_button(text=None, callback=None):
    btn = InlineKeyboardButton(text=text, callback_data=callback)
    return btn


def detach_id_from_callback(query_data):
    additional_query_data = query_data.split(',')[0]
    return additional_query_data


# use callback query answer to show notification on top of the bots chat
def show_error_message(update, context):
    context.bot.send_message(chat_id=context.user_data['chat_id'],
                             text='This engineer is already in db')


def generate_tmp_files(*args):
    res = []
    for suffix in args:
        tmp_file = tempfile.NamedTemporaryFile(suffix=suffix, dir='media/results')
        res.append(tmp_file)
    return res


# ================ HTML TO PDF
# how to call all next functions without update and context args?
def generate_html(update, context):
    proposal = context.user_data['proposal']

    collected_data = proposal.collect_user_data_for_html()

    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('static/index_jinja.html')
    jinja_rendered_html = template.render(**collected_data)
    proposal.html = generate_tmp_files('.html')[0]

    with open(proposal.html.name, 'w+') as html:
        html.write(jinja_rendered_html)

    return generate_pdf(update, context)


def generate_pdf(update, context):
    proposal = context.user_data['proposal']

    pdf_doc = HTML(proposal.html.name)
    pdf_doc_rndr = pdf_doc.render(stylesheets=[CSS('static/main.css')])
    page = pdf_doc_rndr.pages[0]
    child_list = [child for child in page._page_box.descendants()]
    page.height = child_list[2].height
    proposal.pdf = generate_tmp_files('.pdf')[0]
    # pdf_doc.write_pdf(proposal.pdf.name, stylesheets=[CSS('static/main.css')])
    pdf_doc_rndr.write_pdf(target=proposal.pdf.name)

    update.callback_query.answer()

    return send_pdf(context, update)


def send_pdf(context, update):
    proposal = context.user_data['proposal']

    chat_id = context.user_data['chat_id']

    with open(proposal.pdf.name, 'rb') as pdf:
        context.bot.send_document(chat_id=chat_id, document=pdf)

    return ConversationHandler.END


# ================ GENERATE TEST PDF
def get_test_pdf_dict(update, context):
    proposal = context.user_data['proposal']

    proposal.test = True
    update.callback_query.answer()

    return generate_html(update, context)


def end():
    pass


def main():
    updater = Updater(token=TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SELECT_ACTION: [CallbackQueryHandler(init_add_docx,
                            pattern=ADD_DOCX),

                            CallbackQueryHandler(show_buttons,
                            pattern=SHOW_BUTTONS),


                            CallbackQueryHandler(choose_engineers,
                            pattern='^' + str(CHOOSE_ENGINEER) + '$'),

                            CallbackQueryHandler(init_add_new_engineer,
                            pattern=ADD_NEW_ENGINEER),

                            CallbackQueryHandler(add_engineer_to_proposal,
                            pattern=f'.+{ADD_ENGINEER_TO_PROPOSAL}$'),

                            CallbackQueryHandler(init_add_engineers_rate,
                            pattern=ADD_ENGINEERS_RATE),


                            CallbackQueryHandler(edit_title,
                            pattern=f'.+{EDIT_TITLE}$'),

                            CallbackQueryHandler(choose_title_to_edit,
                            pattern=CHOOSE_TITLE_TO_EDIT),


                            CallbackQueryHandler(get_test_pdf_dict,
                            pattern=TEST),


                            CallbackQueryHandler(generate_html,
                            pattern='^' + str(CREATE_PDF) + '$')],

            STORE_DATA: [MessageHandler(Filters.text, store_data)],

            STORE_ENGINEER_TO_DB: [MessageHandler(Filters.photo, store_engineer_to_db)],

            STORE_DOCX: [MessageHandler(Filters.document.docx, store_docx)],
        },

        fallbacks=[CommandHandler('end', end)],

        allow_reentry=True,
         
        per_message=False
     )

    dispatcher.add_handler(conv_handler)

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()