#include "Student.h"

// Implement the required functions here

Student::Student(const string &name, int id, int yearOfStudy, StudentType studentType, Region region, School school):
coursesTaken(nullptr),
partner(nullptr) {
    this->name = name;
    this->id = id;
    this->yearOfStudy = yearOfStudy;
    this->studentType = studentType;
    this->region = region;
    this->school = school;
    this->numTaken = 0;
}

Student::~Student() {
    delete[] this->coursesTaken;
}

Student& Student::enrollCourse(Course &course, Semester semester, int year, const Grades &grade) {
    CourseOffering* the_course_to_take = course.getOffering(semester, year);
    if (the_course_to_take == nullptr)
         the_course_to_take = course.addOffering(semester, year);

    the_course_to_take->assignGrade(this->getId(),grade);
    
    const CourseOffering ** new_coursesTaken = new const CourseOffering* [numTaken+1];
    
    int p=0;
    int q=0;

    if (numTaken == 0) {
        coursesTaken = new_coursesTaken;
        coursesTaken[0] = the_course_to_take;
        numTaken++;
        return *this;
    }

    while (p<numTaken  &&  coursesTaken[p]->compareTo(*the_course_to_take) <0) {
        new_coursesTaken[q] = coursesTaken[p];
        p++;q++;
    }

    
    new_coursesTaken[q] = the_course_to_take;
    q++;

    while (p<numTaken) {
        new_coursesTaken[q] = coursesTaken[p];
        p++;
        q++;
    }
    delete[] coursesTaken;
    coursesTaken = new_coursesTaken;
    numTaken++;
    return *this;
}

void Student::setPartner(const Student *partner){
    this->partner = partner;
};

double Student::calculateScore(const Student &other) const {
    double score=0;
    if (this->yearOfStudy == other.yearOfStudy) score+=SAME_YEAR;
    if (this->studentType == other.studentType) score+=SAME_STUDENT_TYPE;
    if (this->region == other.region) score+= SAME_REGION;
    if (this->school == other.school) score+= SAME_SCHOOL;
    for (int i=0; i<this->numTaken; i++) {
        for (int j=0; j<other.numTaken; j++) {
            if (this->coursesTaken[i]->sameCourse(*other.coursesTaken[j])) {
                if (this->coursesTaken[i]->compareTo(*other.coursesTaken[j]) == 0)
                    score+= SAME_COURSE * SAME_OFFERING_FACTOR;
                else 
                    score+= SAME_COURSE;
            }
        }
    }

    return score;
};



// The following functions are implemented for you.
// DO NOT MODIFY THE LINES BELOW.
int Student::getId() const {
    return id;
}

int Student::getYearOfStudy() const {
    return yearOfStudy;
}

const Student* Student::getPartner() const {
    return partner;
}

void Student::printInfo() const {
    cout << name << " (ID: " << id << ") is a year-" << yearOfStudy << " "
        << studentTypeToString(studentType) << " student. ";

    if (partner) cout << "The study partner of the student has ID of " << partner->getId() << ".";
    else cout << "The student does not have a study partner.";

    cout << endl;
}

void Student::printCourseHistory() const {
    cout << "Courses taken:\n";
    for (int i = 0; i < numTaken; i++) {
        coursesTaken[i]->printInfo();
    }
}

