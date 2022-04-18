<h1 align-text="center">PDF2Exam - PDF Examination 
Question Extraction Tool
</h1>

## Table of Contents
- [Table of Contents](#table-of-contents)
- [Features](#features)
- [Setup](#setup)
- [How to run](#how-to-run)
- [Demo](#demo)
  - [Uncropped full question](#uncropped-full-question)
  - [Cropped Question's Content](#cropped-questions-content)
  - [Cropped Question's Title](#cropped-questions-title)
  - [Cropped answer Option's Title and Content](#cropped-answer-options-title-and-content)
  - [Cropped Explanation](#cropped-explanation)
- [Understanding returned value](#understanding-returned-value)
  - [Question](#question)
  - [Answer Options](#answer-options)
  - [Question's title](#questions-title)
  - [Correct Answer](#correct-answer)
  - [Explanation](#explanation)


##  Features
PDF2Exam is a convenient tool to extract images in pdf tests. PDF2Exam can cut:
- Question's title and question's content
- Answer options's title and Answer options's content
- Correct answers
- Explanation

##  Setup
Install Python 3. </br>
Install fitz.
```sh
pip3 install fitz
```

Install all requirements.
```sh
pip3 install -r requirements.txt 
```


##  How to run 
See the video on how to run the code.

![Demo Video](/images/videos/demo-video.gif)


Run the command below.
```sh
python app.py
```

Go to "http://localhost:5000/". Click "Choose file" and then hit "Submit." PDF2Exam will make a copy of your file in the folder uploads. 

![Upload image](/images/upload-image.png)

After the file finishes processing, you can view the cropped images like below.

![Display image](/images/display.png)

##  Demo

### Uncropped full question 
Here is image of a question before cutting. The result will have cropped images of question's title, question's content, answer option's title and answer option's content.

![Uncropped full question image](/images/uncropped-question.png)

###  Cropped Question's Content

Question's title will be deleted. Question's content are kept.

![Cropped Question](/images/cropped-question.png)

### Cropped Question's Title
Only question title word ("Câu", "Cau", "Bài", "Question") and question number (1,2,3) are included.

![Question Title](/images/title-question.png)

 ### Cropped answer Option's Title and Content

| Answer  Option's title| Answer  Option's content| 
| ------------- |:-------------:|
|![Cropped Title A](/images/a-title.png)|![Cropped Content A](/images/a-content.png)|
|![Cropped Title B](/images/b-title.png)|![Cropped Content A](/images/b-content.png)|
|![Cropped Title C](/images/c-title.png)|![Cropped Content A](/images/c-content.png)|
|![Cropped Title D](/images/d-title.png)|![Cropped Content A](/images/d-content.png)|

### Cropped Explanation
The explanation image will be cropped from the title of the question to the end of that question's explanation.

![Explain](/images/explain.png)
  
  
##  Understanding returned value

At the end of function extract_pdf, the json is returned. The returned values includes information about questions, answers, question's title, and correct answers.

```sh
{
   "questions":"data_question"[0],
   "answers":"data_question"[1],
   "titles":"data_question"[2],
   "correct_options":"correct_answers",
   "explains":"coor_explains_result"
}
```

###  Question

The value of each question contains the page the question is on and the question' coordinates (x0, y0,x1,y1) and base 64 image.

```sh
{
   "question_1":[
      {
         "page":0,
         "coor":[
            36.0,
            338.5330810546875,
            557.1121826171875,
            369.5158386230469,
            "data:<Base 64 image>"
         ]
      }
   ]
}
```

  

###  Answer Options

The answer options will have each option as a list. For the example below, there is only one options. The option's list includes option's title's coordinates (x0,y0,x1,y1) and base 64 image, option's content's coordinates (x0,y0,x1,y1) and base 64 image, and the page the option is on.

```sh
{
   "question_1":{
      "options":[
         [
            54.0,
            381.00201416015625,
            68.66400146484375,
            397.62200927734375,
            "data:<Base 64 image>",
            68.66400146484375,
            369.5158386230469,
            189.02000427246094,
            409.63446044921875,
            "data:<Base 64 image>",
            0
         ]
      ]
   }
}
```

###  Question's title

  

Question's title will be returned in a dictionary. The value contains question's title's coordinates (x0,y0,x1,y1) and a base 64 image.

```sh
{
   "question_1":[
      36.0,
      341.0419921875,
      70.33200073242188,
      357.6620178222656,
      "data:<Base 64 image>"
   ]
}
```

  

###  Correct Answer

Correct Answers will be returned in a dictionary. The key is the question and the value is the correct answer to that question

```sh
{
   "question_1":"D",
   "question_2":"C",
   "question_3":"B"
}
```

###  Explanation

Explanation will be returned in a dictionary. The key is the question and the value is the coordinates (x0,y0,x1,y1) and a base 64 image.

```sh
{
   "question_1":[
      106.22000122070312,
      44.600006103515625,
      457.7799987792969,
      372.468994140625,
      "data:<Base 64 image>"
   ]
}
```

  

