import tensorflow as tf
from environment import Environment
from simple_fontain import SimpleFontain, SimpleFontainBatcher
from some_useful_functions import load_vocabulary_from_file, get_positions_in_vocabulary

f = open('small_flagged_subs.txt', 'r', encoding='utf-8')
text = f.read()
f.close()

# different
offset = 102
valid_size = 100
valid_text = text[-offset:-offset + valid_size]
# print('valid_text:', valid_text)

#train_text = text[0:-offset]
train_text = text[-offset-1000:-offset]
train_size = len(train_text)

vocabulary = load_vocabulary_from_file('subs_vocabulary.txt')

cpiv = get_positions_in_vocabulary(vocabulary)

vocabulary_size = len(vocabulary)
#print(vocabulary_size)

env = Environment(SimpleFontain, SimpleFontainBatcher)
env.build(batch_size=64,
          vocabulary_size=vocabulary_size,
          attention_interval=3,
          attention_visibility=5,
          subsequence_length_in_intervals=7,
          characters_positions_in_vocabulary=cpiv)

def count_non_zeros(**kwargs):
    tensor = kwargs['tensor']
    return tf.reduce_sum(tf.to_float(tf.not_equal(tensor, 0.)))

def l2_norm(**kwargs):
    tensor = kwargs['tensor']
    shape = tensor.get_shape().as_list()
    num_elem = 1
    for dim in shape:
        num_elem *= dim
    return tf.sqrt(2 * tf.nn.l2_loss(tensor) / num_elem)

def first_element(**kwargs):
    tensor = kwargs['tensor']
    shape = tensor.get_shape().as_list()
    batch_size = shape[1]
    first_elem = tf.reshape(tf.split(tensor, [1, batch_size-1], axis=1)[0], [-1])
    return first_elem

env.register_build_function(count_non_zeros, 'count_nz')
env.register_build_function(l2_norm, 'l2_norm')
env.register_build_function(first_element, 'first_element')

def saved_states_nz_schedule():
    tmpl = "train/saved_state_layer%s_number%s:0"
    schedule = dict()
    for i in range(3):
        for j in range(2):
            hook_name = 'nz_ss_l%s_n%s' % (i, j)
            env.register_builder('count_nz',
                                 tensor_names={'tensor': tmpl % (i, j)},
                                 output_hook_name=hook_name)
            schedule[hook_name] = [i for i in range(30)]
    return schedule


def matrices_l2_schedule(length):
    tmpl = "LSTM_matrix_%s"
    schedule = dict()
    for i in range(3):
        hook_name = (tmpl + '_l2') % i
        env.register_builder('l2_norm',
                             tensor_names={'tensor': (tmpl + ':0') % i},
                             output_hook_name=hook_name)
        schedule[hook_name] = [i for i in range(length)]
    hook_name = 'emb_matr_l2'
    env.register_builder('l2_norm',
                         tensor_names={'tensor': 'embedding_matrix:0'},
                         output_hook_name=hook_name)
    schedule[hook_name] = [i for i in range(length)]
    hook_name = 'out_emb_matr_l2'
    env.register_builder('l2_norm',
                         tensor_names={'tensor': 'output_embedding_matrix:0'},
                         output_hook_name=hook_name)
    schedule[hook_name] = [i for i in range(length)]
    hook_name = 'out_matr_l2'
    env.register_builder('l2_norm',
                         tensor_names={'tensor': 'output_matrix:0'},
                         output_hook_name=hook_name)
    schedule[hook_name] = [i for i in range(length)]
    return schedule

def cell_states_l2(length):
    tmpl = "train/saved_state_layer%s_number1:0"
    schedule = dict()
    for i in range(3):
        hook_name = 'l2_ss_l%s_n1' % i
        env.register_builder('l2_norm',
                                 tensor_names={'tensor': tmpl % i},
                                 output_hook_name=hook_name)
        schedule[hook_name] = [i for i in range(length)]
    return schedule

def eod_flags(length):
    schedule = dict()
    env.register_builder('first_element',
                         tensor_names={'tensor': "train/inputs_and_flags:2"},
                         output_hook_name='eod_flags')
    schedule['eod_flags'] = [i for i in range(length)]
    return schedule

def bot_answer_flags(length):
    schedule = dict()
    env.register_builder('first_element',
                         tensor_names={'tensor': "train/inputs_and_flags:1"},
                         output_hook_name='bot_answer_flags')
    schedule['bot_answer_flags'] = [i for i in range(length)]
    return schedule

# schedule = matrices_l2_schedule(30)
# schedule.update(cell_states_l2(30))
# schedule = bot_answer_flags(30)

#env.print_available_builders()

# env.train(save_path='debugging_simple_fontain/first',
#           learning_rate={'type': 'exponential_decay',
#                          'init': 3.,
#                          'decay': .9,
#                          'period': 500},
#           batch_size=64,
#           vocabulary=vocabulary,
#           checkpoint_steps=[100],
#           stop=1000,
#           num_unrollings=21,
#           #debug=0,
#           #train_dataset_text='abx',
#           #validation_datasets_texts=['abc'],
#           train_dataset_text=train_text,
#           validation_dataset_texts=[valid_text],
#           printed_result_types=['loss', 'perplexity', 'accuracy'],
#           #add_graph_to_summary=True,
#           #validation_dataset=[valid_text],
#           results_collect_interval=50
#           #no_validation=True,
#           #train_print_tensors=schedule
#           )

evaluation = dict(
    save_path='simple_fontain/tuning',
    result_types=['perplexity', 'loss', 'bpc', 'accuracy'],
    datasets={'train': None,
              'default_1': [valid_text, 'default_1']},
    batch_gen_class=SimpleFontainBatcher,
    batch_kwargs={'vocabulary': vocabulary},
    batch_size=1,
    additional_feed_dict=None
)

kwargs_for_building = dict(
          batch_size=64,
          vocabulary_size=vocabulary_size,
          attention_interval=3,
          attention_visibility=5,
          subsequence_length_in_intervals=7,
          characters_positions_in_vocabulary=cpiv)

list_of_lr = [dict(type='exponential_decay', init=v, decay=.9, period=500) for v in [10., 5., 3., 1., .3]]

env.several_launches(evaluation,
                     kwargs_for_building,
                     build_hyperparameters={'init_parameter': [.01, .03, .1, .3, 1., 3.]},
                     other_hyperparameters={'learning_rate': list_of_lr},
                     batch_size=64,
                     vocabulary=vocabulary,
                     stop=100,
                     num_unrollings=21,
                     train_dataset_text=train_text,
                     printed_result_types=['loss', 'perplexity', 'accuracy'],
                     results_collect_interval=None,
                     no_validation=True,
                     additional_feed_dict=None)