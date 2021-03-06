import os
import logging
import csv
from collections import defaultdict
import numpy as np
from nltk.stem import WordNetLemmatizer
from keras.preprocessing.sequence import pad_sequences
from keras.utils.np_utils import to_categorical

from util import preprocess


class Data(object):

    token2idx = {'PADDING': 0, 'UNKNOWN': 1}
    feature2idx = defaultdict(lambda : {'PADDING': 0, 'UNKNOWN': 1})
    label2idx = {'PADDING': 0}
    tokenIdx2charVector = []
    wordEmbedding = []
    casing2idx = {}
    tokenIdx2casingVector = []

    lemmatizer = WordNetLemmatizer()

    sentences = None
    labels = None
    features = None

    def __init__(self, inputPathList, testPath, freqCutOff=1):

        tokenFreq = preprocess.tokenFrequency(inputPathList + [testPath])
        for token, freq in sorted(tokenFreq.items(), key=lambda kv: kv[0]):
            if token not in self.token2idx and freq >= freqCutOff:
                self.token2idx[token] = len(self.token2idx)
        self.feature2idx, self.label2idx = preprocess.featureLabelIndex(inputPathList)
        self.char2idx = preprocess.getChar2idx()

        tokenLengthDistribution = preprocess.tokenLengthDistribution(self.token2idx)
        self.maxTokenLen = preprocess.selectPaddingLength(tokenLengthDistribution, ratio=0.99)
        logging.info('Max token length: ' + str(self.maxTokenLen))

        sentenceLengthDistribution = preprocess.sentenceLengthDistribution(inputPathList + [testPath])
        self.maxSentenceLen = preprocess.selectPaddingLength(sentenceLengthDistribution, ratio=0.999)
        logging.info('Max sentence length: ' + str(self.maxSentenceLen))

        self.vocabSize = len(self.token2idx)
        logging.info('Vocabulary size: ' + str(self.vocabSize))

        self.labelDim = len(self.label2idx)
        logging.info('Label dim: ' + str(self.labelDim))

        self.initToken2charVector()
        self.initWordEmbedding()
        self.casing2idx = preprocess.getCasing2idx()
        self.initTokenIdx2casingVector()

    def initToken2charVector(self):
        tokenIdx2charVector = []
        for token, idx in sorted(self.token2idx.items(), key=lambda kv: kv[1]):
            if idx >= 2:
                charVector = list(map(lambda c: self.char2idx.get(c, 1), token))    # 1 for UNKNOWN char
            else:
                charVector = [0]  # PADDING
            tokenIdx2charVector.append(charVector)

        self.tokenIdx2charVector = np.asarray(pad_sequences(tokenIdx2charVector, maxlen=self.maxTokenLen))
        logging.debug(self.tokenIdx2charVector.shape)

    def initTokenIdx2casingVector(self):
        tokenIdx2casingVector = []
        for token, idx in sorted(self.token2idx.items(), key=lambda kv: kv[1]):
            if idx >= 2:
                casingVector = preprocess.getCasing(token)
                tokenIdx2casingVector.append(casingVector)
            elif idx == 1:
                casingVector = np.zeros(len(self.casing2idx))
                casingVector[0] = 1
                tokenIdx2casingVector.append(casingVector)
            else:
                casingVector = np.zeros(len(self.casing2idx))
                tokenIdx2casingVector.append(casingVector)
        self.tokenIdx2casingVector = np.asarray(tokenIdx2casingVector)
        logging.debug(self.tokenIdx2casingVector.shape)

    def initWordEmbedding(self, dim=100):
        """        
        The tokens in the word embedding matrix are uncased 
        """
        notInPretrained = 0
        foundLemmatized = 0
        word2vector = preprocess.loadWordEmbedding('data/glove.6B.100d.txt', dim=dim)
        for token, idx in sorted(self.token2idx.items(), key=lambda kv: kv[1]):
            if idx >= 2:
                token = token.lower()
            if token in word2vector:
                vector = word2vector[token]
            else:
                token = self.lemmatizer.lemmatize(token)
                if token in word2vector:
                    vector = word2vector[token]
                    foundLemmatized += 1
                else:
                    vector = np.random.uniform(-0.25, 0.25, dim)
                    notInPretrained += 1
            self.wordEmbedding.append(vector)

        self.wordEmbedding = np.asarray(self.wordEmbedding)

        logging.info('Tokens not in pretrained: {}'.format(notInPretrained))
        logging.info('Lemmatized token in pretrained: {}'.format(foundLemmatized))
        logging.debug(self.wordEmbedding[0])
        logging.debug(self.wordEmbedding.shape)



    def loadCoNLL(self, filePath, loadFeatures=False, mode='train'):
        assert mode in ['train', 'test']

        sentences = [[]]
        if loadFeatures:
            features = defaultdict(lambda : [[]])
        if mode == 'train':
            labels = [[]]

        with open(filePath, 'r', encoding='utf-8') as inputFile:

            for line in inputFile:
                line = line.strip('\n')
                if not line:
                    sentences.append([])
                    if mode == 'train':
                        labels.append([])

                    if loadFeatures:
                        for featureList in features.values():
                            featureList.append([])

                else:
                    data_tuple = line.split('\t')

                    token = data_tuple[0]
                    tokenIdx = self.token2idx.get(token, 1) # 1 for UNKNOWN
                    sentences[-1].append(tokenIdx)

                    if mode == 'train':
                        labelIdx = self.label2idx[data_tuple[-1]]
                        labels[-1].append(labelIdx)

                    if loadFeatures:
                        if mode == 'train':
                            featureTuple = data_tuple[1:-1]
                        else:
                            featureTuple = data_tuple[1:]
                        for idx, feature in enumerate(featureTuple):
                            featureIdx = self.feature2idx[idx].get(feature, 1)
                            features[idx][-1].append(featureIdx)
        if mode == 'train':
            # Pad sentence to the longest length
            sentences = pad_sequences(sentences, maxlen=self.maxSentenceLen)

            # Transform labels to one hot encoding
            labels = np.expand_dims(pad_sequences(labels, maxlen=self.maxSentenceLen), -1)

            for idx in features:
                features[idx] = pad_sequences(features[idx], maxlen=self.maxSentenceLen)

        if loadFeatures:
            return_data = [sentences]
            for idx in range(len(features)):
                return_data.append(features[idx])
            if mode == 'train':
                return_data.append(labels)
            return return_data
        else:
            if mode == 'train':
                return sentences, labels
            elif mode == 'test':
                return sentences


    def predict(self, model, testPath, outputPath):

        logging.info('Begin predict...')

        idx2token = {v: k for k,v in self.token2idx.items()}
        idx2label = {v: k for k, v in self.label2idx.items()}
        with open(testPath, 'r', encoding='utf-8') as inputFile:
            with open(outputPath, 'w', encoding='utf-8') as outputFile:

                reader = csv.reader(inputFile, delimiter=',', quotechar='"')
                _ = reader.__next__()

                sentences = defaultdict(list)
                for row in reader:
                    sentID = int(row[0])
                    sentences[sentID].append(row)


                for sentID, sent in sorted(sentences.items(), key=lambda kv: kv[0]):
                    rawSentence = list(map(lambda t: t[-1], sent))

                    x, y = self.predictRaw(model, rawSentence)
                    tokenID = 0

                    for tokenIdx, labelIdx in zip(x, y):
                        if tokenIdx != 0:
                            token = idx2token[tokenIdx]
                            label = idx2label[labelIdx]
                            outputFile.write('{}\t{}\t{}\t{}\n'.format(sentID, tokenID, label, token))
                            tokenID += 1


    def predictRaw(self, model, rawSent):

        sentence = np.asarray(tuple(map(lambda t: self.token2idx.get(t, 1), rawSent)))
        sentLen = len(rawSent)
        maxLen = self.maxSentenceLen

        if sentLen > maxLen:

            sentence_parts = []
            for idx in range(sentLen // maxLen):
                sentence_parts.append(np.asarray(sentence[idx * maxLen:(idx + 1) * maxLen]))
            if sentLen % maxLen != 0:
                sentence_parts.append(np.asarray(sentence[sentLen // maxLen * maxLen:]))
            sentence_parts = pad_sequences(sentence_parts, maxlen=maxLen)
            y_parts = model.predict_on_batch(sentence_parts)

            x = sentence_parts.flatten()
            y = y_parts.argmax(axis=-1).flatten()

        else:
            sentence = pad_sequences([sentence], maxlen=maxLen)
            y_predict = model.predict_on_batch(sentence)

            x = sentence.flatten()
            y = y_predict.argmax(axis=-1).flatten()

        return x, y

    def predictWithFeature(self, model, X_test, outputPath):

        logging.info('Begin predict...')

        idx2token = {v: k for k,v in self.token2idx.items()}
        idx2label = {v: k for k, v in self.label2idx.items()}
        with open(outputPath, 'w', encoding='utf-8') as outputFile:

            sentID = 0
            for x_sent in zip(*X_test):

                x, y = self.predictX(model, x_sent)
                tokenID = 0

                for tokenIdx, labelIdx in zip(x, y):
                    if tokenIdx != 0:
                        token = idx2token[tokenIdx]
                        label = idx2label[labelIdx]
                        outputFile.write('{}\t{}\t{}\t{}\n'.format(sentID, tokenID, label, token))
                        tokenID += 1
                sentID += 1
        logging.info('Finish prediction')

    def predictX(self, model, x_sent):

        sentLen = len(x_sent[0])
        maxLen = self.maxSentenceLen

        x_parts = []
        for i in range(len(x_sent)):
            x_parts.append([])
        if sentLen > maxLen:

            for idx in range(sentLen // maxLen):
                for i in range(len(x_sent)):
                    x_parts[i].append(np.asarray(x_sent[i][idx * maxLen:(idx + 1) * maxLen]))
            if sentLen % maxLen != 0:
                for i in range(len(x_sent)):
                    x_parts[i].append(np.asarray(x_sent[i][sentLen // maxLen * maxLen:]))

            for i in range(len(x_sent)):
                x_parts[i] = pad_sequences(x_parts[i], maxlen=maxLen)
            y_parts = model.predict_on_batch(x_parts)

            y = y_parts.argmax(axis=-1).flatten()

        else:
            for i in range(len(x_sent)):
                x_parts[i] = pad_sequences([x_sent[i]], maxlen=maxLen)
            y_predict = model.predict_on_batch(x_parts)

            y = y_predict.argmax(axis=-1).flatten()

        x = x_parts[0].flatten()

        return x, y


    @staticmethod
    def validPrediction(predictPath, testPath):
        with open(testPath, 'r', encoding='utf-8') as testFile:
            with open(predictPath, 'r', encoding='utf-8') as predFile:
                reader = csv.reader(testFile, delimiter=',', quotechar='"')
                reader.__next__()
                for pred, test in zip(predFile, reader):
                    predTuple = pred.strip('\n').split('\t')
                    if predTuple[3] != 'UNKNOWN':
                        assert predTuple[0] == test[0], str(pred) + str(test)
                        assert predTuple[1] == test[1], str(pred) + str(test)
                        assert predTuple[3] == test[2], str(pred) + str(test)
        return 0

